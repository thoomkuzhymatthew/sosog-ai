"""Build bounded, family-level coding jobs from task-level trace evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .workflow import ACTION_DESIGNS


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a local input artifact."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _candidate_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["task_id"]): item for item in plan.get("candidates", [])}


def _evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    value = candidate.get("evidence")
    return value if isinstance(value, dict) else candidate


def validate_family_config(plan: dict[str, Any], family_config: dict[str, Any]) -> None:
    """Reject ambiguous, overlapping, or unsupported family specifications."""

    if family_config.get("schema_version") != 1:
        raise ValueError("family config schema_version must be 1")
    if family_config.get("vertical") != plan.get("vertical"):
        raise ValueError("family config vertical must match the promotion plan")
    families = family_config.get("families")
    if not isinstance(families, list) or not families:
        raise ValueError("family config must contain at least one family")

    candidates = _candidate_map(plan)
    seen_family_ids: set[str] = set()
    seen_job_ids: set[str] = set()
    seen_training_tasks: set[str] = set()
    seen_evaluation_sets: set[str] = set()
    for family in families:
        family_id = str(family.get("family_id") or "")
        job_id = str(family.get("job_id") or "")
        evaluation_set_id = str(family.get("evaluation_set_id") or "")
        action = str(family.get("action") or "")
        training_ids = [str(value) for value in family.get("training_task_ids", [])]
        allowed_paths = family.get("allowed_changed_paths")
        if not family_id or family_id in seen_family_ids:
            raise ValueError(f"missing or duplicate family_id: {family_id!r}")
        if not job_id or job_id in seen_job_ids:
            raise ValueError(f"missing or duplicate job_id: {job_id!r}")
        if not evaluation_set_id or evaluation_set_id in seen_evaluation_sets:
            raise ValueError(
                f"missing or duplicate evaluation_set_id: {evaluation_set_id!r}"
            )
        if action not in ACTION_DESIGNS or not ACTION_DESIGNS[action]["coding_job"]:
            raise ValueError(f"unsupported family action: {action}")
        if not training_ids:
            raise ValueError(f"family {family_id} has no training tasks")
        overlap = seen_training_tasks.intersection(training_ids)
        if overlap:
            raise ValueError(f"training tasks appear in multiple families: {overlap}")
        if not isinstance(allowed_paths, list) or not allowed_paths:
            raise ValueError(f"family {family_id} has no allowed changed paths")
        if len(set(allowed_paths)) != len(allowed_paths):
            raise ValueError(f"family {family_id} repeats an allowed path")
        if int(family.get("max_changed_files", 0)) < 1:
            raise ValueError(f"family {family_id} has an invalid file budget")
        if int(family.get("max_diff_bytes", 0)) < 1:
            raise ValueError(f"family {family_id} has an invalid diff budget")

        for task_id in training_ids:
            candidate = candidates.get(task_id)
            if candidate is None:
                raise ValueError(f"training task {task_id} is missing from the plan")
            if str(candidate.get("action")) != action:
                raise ValueError(
                    f"training task {task_id} is {candidate.get('action')}, not {action}"
                )

        seen_family_ids.add(family_id)
        seen_job_ids.add(job_id)
        seen_evaluation_sets.add(evaluation_set_id)
        seen_training_tasks.update(training_ids)


def _family_prompt(
    *,
    family: dict[str, Any],
    training_evidence: list[dict[str, Any]],
    training_trace_path: str,
    training_trace_sha256: str,
    training_tasks_path: str,
    training_tasks_sha256: str,
    evaluation_manifest_sha256: str,
    tau2_dependency: dict[str, Any],
) -> str:
    action = str(family["action"])
    design = ACTION_DESIGNS[action]
    paths = "\n".join(f"- `{path}`" for path in family["allowed_changed_paths"])
    evidence_lines = "\n".join(
        "- task {task_id}: N={n}, pass_rate={pass_rate}, "
        "mean_cost_usd={mean_cost}, writes={writes}".format(
            task_id=item["task_id"],
            n=item["n"],
            pass_rate=item["pass_rate"],
            mean_cost=item["mean_cost_usd"],
            writes=item["write_name_patterns"],
        )
        for item in training_evidence
    )
    allowed_writes = ", ".join(family["allowed_write_tools"])
    return f"""You are an isolated SOSOG coding worker for the Airline `{family['family_id']}` family.

Your current directory is a detached SOSOG Git worktree. The τ2 dependency is
read-only at `{tau2_dependency['runtime_path']}` and is pinned to commit
`{tau2_dependency['commit']}`. Do not modify that dependency.

Classification: `{action}`
Job type: `{design['coding_job']}`
Required runtime: {' -> '.join(design['runtime_path'])}
Required fallback: `{design['fallback']}`
Allowed write tools: {allowed_writes}

Training evidence:
{evidence_lines}

Use only these frozen public derivation inputs:

- `{training_trace_path}` (SHA-256 `{training_trace_sha256}`)
- `{training_tasks_path}` (SHA-256 `{training_tasks_sha256}`)
- `config/airline_write_tools.json`
- the pinned τ2 policy, DB models, tool contracts and evaluator implementation

An independent controller owns evaluation set `{family['evaluation_set_id']}`
with manifest SHA-256 `{evaluation_manifest_sha256}`. Its cases are deliberately
not included in this prompt. Do not search for benchmark tasks outside the
provided training-task artifact or attempt to infer the held-out IDs. Do not
modify an evaluator, benchmark task, policy, database fixture or promotion
threshold.

Implement a parameterized executor that accepts structured intent and follows
`crystallized.airline.contracts`. Instance identifiers must be resolved or
validated at runtime; do not present fixed trace arguments as a family solution.
Validate the complete intent before the first write. On ambiguity, unsupported
policy, conflicting state or an unproven invariant, return `DEFERRED` with zero
writes so the full agent can take over. The executor itself must make zero model
calls.

You may change exactly these files:
{paths}

The host will reject every other changed path, more than
{family['max_changed_files']} changed files, or a diff above
{family['max_diff_bytes']} bytes. Do not commit, merge, push, deploy, access
credentials or enable network access.

Add focused tests using fake tools for schema failures, state conflicts, safe
deferral and a successful parameterized path. When possible, also exercise the
local τ2 programmatic verifier. Run the tests. In the evidence note distinguish
completed behavior, safe deferrals and wrong writes; report model calls, test
commands, changed files and unresolved safety questions. Your work is a
proposal and cannot approve itself for promotion.
"""


def build_family_coding_jobs(
    plan: dict[str, Any],
    family_config: dict[str, Any],
    *,
    artifact_root: Path,
    controller_evaluation_hashes: dict[str, str],
    max_jobs: int = 3,
) -> list[dict[str, Any]]:
    """Create reproducible family jobs without exposing held-out task IDs."""

    if max_jobs < 1:
        raise ValueError("max_jobs must be at least one")
    validate_family_config(plan, family_config)
    candidates = _candidate_map(plan)
    vertical = str(plan["vertical"])
    tau2_dependency = family_config["tau2_dependency"]
    jobs: list[dict[str, Any]] = []

    for family in family_config["families"][:max_jobs]:
        family_id = str(family["family_id"])
        evaluation_set_id = str(family["evaluation_set_id"])
        evaluation_hash = controller_evaluation_hashes.get(evaluation_set_id)
        if not evaluation_hash:
            raise ValueError(
                f"missing controller evaluation hash for {evaluation_set_id}"
            )
        trace_rel = f"metrics/m18_airline_promotion/training_traces/{family_id}.jsonl"
        tasks_rel = f"metrics/m18_airline_promotion/training_tasks/{family_id}.json"
        trace_path = artifact_root / trace_rel
        tasks_path = artifact_root / tasks_rel
        if not trace_path.is_file() or not tasks_path.is_file():
            raise ValueError(f"training package is missing for family {family_id}")

        evidence = []
        for task_id in family["training_task_ids"]:
            candidate = candidates[str(task_id)]
            item = _evidence(candidate)
            evidence.append(
                {
                    "task_id": str(task_id),
                    "n": int(item.get("n", 0)),
                    "pass_rate": float(item.get("pass_rate", 0)),
                    "mean_cost_usd": float(item.get("mean_cost_usd", 0)),
                    "write_name_patterns": item.get("write_name_patterns", []),
                }
            )

        manifest = {
            "schema_version": 2,
            "job_id": family["job_id"],
            "family_id": family_id,
            "vertical": vertical,
            "action": family["action"],
            "allowed_changed_paths": family["allowed_changed_paths"],
            "max_changed_files": family["max_changed_files"],
            "max_diff_bytes": family["max_diff_bytes"],
            "require_changes": True,
            "permissions": {
                "may_commit": False,
                "may_merge": False,
                "may_push": False,
                "may_deploy": False,
                "network_access": False,
            },
            "inputs": {
                "training_trace": {
                    "path": trace_rel,
                    "sha256": sha256_file(trace_path),
                },
                "training_tasks": {
                    "path": tasks_rel,
                    "sha256": sha256_file(tasks_path),
                },
                "training_task_ids": family["training_task_ids"],
                "tau2_dependency": tau2_dependency,
            },
            "evaluation": {
                "controller_owned": True,
                "manifest_sha256": evaluation_hash,
                "set_id": evaluation_set_id,
                "visible_to_worker": False,
            },
            "required_review_stages": [
                "INDEPENDENT_HELD_OUT",
                "ADVERSARIAL_DEFERRAL",
                "HUMAN_SAFETY_REVIEW",
                "SHADOW_ECONOMICS",
            ],
        }
        prompt = _family_prompt(
            family=family,
            training_evidence=evidence,
            training_trace_path=trace_rel,
            training_trace_sha256=manifest["inputs"]["training_trace"]["sha256"],
            training_tasks_path=tasks_rel,
            training_tasks_sha256=manifest["inputs"]["training_tasks"]["sha256"],
            evaluation_manifest_sha256=evaluation_hash,
            tau2_dependency=tau2_dependency,
        )
        jobs.append(
            {
                "job_id": family["job_id"],
                "family_id": family_id,
                "action": family["action"],
                "prompt": prompt,
                "manifest": manifest,
                "requires_human_safety_review": True,
                "may_merge_or_deploy": False,
            }
        )
    return jobs


def canonical_json_sha256(value: Any) -> str:
    """Hash a JSON value using the canonical representation used by manifests."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()
