#!/usr/bin/env python3
"""Freeze family derivation inputs and emit bounded coding-worker jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from promotion_engine.family_jobs import (  # noqa: E402
    build_family_coding_jobs,
    canonical_json_sha256,
    sha256_file,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_promotion_pipeline import load_trace_rows  # noqa: E402

_INFRASTRUCTURE_TERMINATIONS = {
    "api_error",
    "daily_quota_error",
    "infrastructure_error",
    "model_unavailable",
    "quota_error",
    "rate_limit_error",
    "timeout",
}


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _is_complete(row: dict[str, Any]) -> bool:
    termination = str(row.get("termination_reason") or "").strip().lower()
    if termination in _INFRASTRUCTURE_TERMINATIONS or any(
        token in termination for token in ("infrastructure", "quota", "rate_limit")
    ):
        return False
    return str(row.get("status") or "").strip().upper() == "COMPLETE"


def _task_id(value: dict[str, Any]) -> str:
    return str(value.get("task_id", value.get("id", "")))


def _sort_row(row: dict[str, Any]) -> tuple[str, int, int, str]:
    return (
        _task_id(row),
        int(row.get("trial") or 0),
        int(row.get("seed") or 0),
        str(row.get("run_id") or ""),
    )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        )
    )


def _freeze_training_inputs(
    *,
    rows: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    family_config: dict[str, Any],
    output_dir: Path,
) -> None:
    task_map = {_task_id(task): task for task in tasks}
    complete_rows = [row for row in rows if _is_complete(row)]
    for family in family_config["families"]:
        family_id = str(family["family_id"])
        training_ids = {str(value) for value in family["training_task_ids"]}
        missing = training_ids.difference(task_map)
        if missing:
            raise ValueError(
                f"training task definitions are missing: {sorted(missing)}"
            )
        selected_rows = sorted(
            [row for row in complete_rows if _task_id(row) in training_ids],
            key=_sort_row,
        )
        observed_ids = {_task_id(row) for row in selected_rows}
        if observed_ids != training_ids:
            raise ValueError(
                f"complete training traces are missing for {sorted(training_ids - observed_ids)}"
            )
        _write_jsonl(
            output_dir / "training_traces" / f"{family_id}.jsonl", selected_rows
        )
        _write_json(
            output_dir / "training_tasks" / f"{family_id}.json",
            [task_map[task_id] for task_id in sorted(training_ids)],
        )


def _freeze_controller_evaluations(
    *,
    tasks: list[dict[str, Any]],
    family_config: dict[str, Any],
    controller_config: dict[str, Any],
    trace_source: str,
    trace_source_sha256: str,
    tasks_sha256: str,
    output_dir: Path,
) -> dict[str, str]:
    task_map = {_task_id(task): task for task in tasks}
    evaluation_sets = controller_config.get("evaluation_sets")
    if not isinstance(evaluation_sets, dict):
        raise ValueError("controller config requires evaluation_sets")
    hashes: dict[str, str] = {}
    training_ids = {
        str(task_id)
        for family in family_config["families"]
        for task_id in family["training_task_ids"]
    }
    expected_set_ids = {
        str(family["evaluation_set_id"]) for family in family_config["families"]
    }
    if set(evaluation_sets) != expected_set_ids:
        raise ValueError("controller evaluation sets must exactly match family config")

    for set_id in sorted(evaluation_sets):
        spec = evaluation_sets[set_id]
        heldout_ids = [str(value) for value in spec.get("heldout_task_ids", [])]
        if not heldout_ids:
            raise ValueError(f"evaluation set {set_id} has no held-out tasks")
        overlap = training_ids.intersection(heldout_ids)
        if overlap:
            raise ValueError(f"evaluation tasks leaked into training inputs: {overlap}")
        missing = set(heldout_ids).difference(task_map)
        if missing:
            raise ValueError(
                f"held-out task definitions are missing: {sorted(missing)}"
            )
        manifest = {
            "schema_version": 1,
            "set_id": set_id,
            "vertical": family_config["vertical"],
            "heldout_task_ids": heldout_ids,
            "heldout_tasks": [task_map[task_id] for task_id in heldout_ids],
            "adversarial_cases": spec.get("adversarial_cases", []),
            "promotion_requirements": spec.get(
                "promotion_requirements",
                {
                    "max_wrong_writes": 0,
                    "require_no_writes_on_deferral": True,
                    "require_programmatic_verifier": True,
                    "require_human_safety_review": True,
                },
            ),
            "provenance": {
                "frozen_at": controller_config.get("frozen_at"),
                "tasks_json_sha256": tasks_sha256,
                "trace_source": trace_source,
                "trace_source_sha256": trace_source_sha256,
                "tau2_dependency": family_config["tau2_dependency"],
            },
        }
        digest = canonical_json_sha256(manifest)
        manifest["canonical_sha256"] = digest
        _write_json(output_dir / f"{set_id}.json", manifest)
        hashes[set_id] = digest
    _write_json(output_dir / "hashes.json", hashes)
    return hashes


def _write_jobs(output_dir: Path, jobs: list[dict[str, Any]]) -> None:
    output_dir = output_dir.resolve()
    jobs_dir = output_dir / "coding_jobs"
    manifests_dir = jobs_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    public_jobs = []
    for job in jobs:
        job_id = str(job["job_id"])
        prompt_path = jobs_dir / f"{job_id}.md"
        manifest_path = manifests_dir / f"{job_id}.json"
        prompt_path.write_text(job["prompt"].rstrip() + "\n")
        _write_json(manifest_path, job["manifest"])
        public_jobs.append(
            {
                "action": job["action"],
                "family_id": job["family_id"],
                "job_id": job_id,
                "manifest_path": str(manifest_path.relative_to(ROOT)),
                "manifest_sha256": sha256_file(manifest_path),
                "may_merge_or_deploy": False,
                "prompt_path": str(prompt_path.relative_to(ROOT)),
                "prompt_sha256": sha256_file(prompt_path),
                "requires_human_safety_review": True,
            }
        )
    _write_json(jobs_dir / "jobs.json", public_jobs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_jsonl", help="local path or s3:// URI")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--family-config", required=True, type=Path)
    parser.add_argument("--controller-config", required=True, type=Path)
    parser.add_argument("--tasks-json", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--controller-output-dir", required=True, type=Path)
    parser.add_argument("--max-jobs", type=int, default=3)
    args = parser.parse_args()

    rows = load_trace_rows(args.trace_jsonl)
    plan = _load_object(args.plan)
    family_config = _load_object(args.family_config)
    controller_config = _load_object(args.controller_config)
    tasks_value = json.loads(args.tasks_json.read_text())
    if not isinstance(tasks_value, list):
        raise ValueError("tasks JSON must contain a list")

    if args.trace_jsonl.startswith("s3://"):
        trace_digest = hashlib.sha256(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in rows
            ).encode()
        ).hexdigest()
    else:
        trace_digest = sha256_file(Path(args.trace_jsonl))
    tasks_digest = sha256_file(args.tasks_json)

    _freeze_training_inputs(
        rows=rows,
        tasks=tasks_value,
        family_config=family_config,
        output_dir=args.output_dir,
    )
    controller_hashes = _freeze_controller_evaluations(
        tasks=tasks_value,
        family_config=family_config,
        controller_config=controller_config,
        trace_source=args.trace_jsonl,
        trace_source_sha256=trace_digest,
        tasks_sha256=tasks_digest,
        output_dir=args.controller_output_dir,
    )
    jobs = build_family_coding_jobs(
        plan,
        family_config,
        artifact_root=ROOT,
        controller_evaluation_hashes=controller_hashes,
        max_jobs=args.max_jobs,
    )
    _write_jobs(args.output_dir, jobs)
    plan["family_job_package"] = {
        "schema_version": 1,
        "controller_evaluation_hashes": controller_hashes,
        "job_ids": [job["job_id"] for job in jobs],
        "strategy": "family_level_derivation_with_controller_owned_evaluation",
    }
    plan.setdefault("summary", {})["coding_jobs_emitted"] = len(jobs)
    _write_json(args.output_dir / "promotion_plan.json", plan)
    print(
        json.dumps(
            {
                "controller_evaluation_hashes": controller_hashes,
                "jobs": [job["job_id"] for job in jobs],
                "output_dir": str(args.output_dir),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
