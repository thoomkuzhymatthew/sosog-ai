#!/usr/bin/env python3
"""Normalize one AppWorld experiment into S3 rows and the research index."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_ops.persistence import ResearchStore, StoreConfig  # noqa: E402


def usage_cost(usage: dict[str, Any]) -> float:
    return round(sum(float(value or 0) for value in usage.get("cost", {}).values()), 10)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--trial", type=int, required=True)
    parser.add_argument("--route-map", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    output_dir = args.root / "experiments" / "outputs" / args.experiment
    evaluation = json.loads(
        (output_dir / "evaluations" / f"{args.dataset}.json").read_text()
    )
    route_map = json.loads(args.route_map.read_text())
    task_ids = [
        line.strip()
        for line in (args.root / "data" / "datasets" / f"{args.dataset}.txt").read_text().splitlines()
        if line.strip()
    ]
    store = ResearchStore(StoreConfig.from_env())
    store.record_run(
        {
            "run_id": args.run_id,
            "milestone": "M14",
            "vertical": "appworld",
            "status": "RUNNING",
            "subject_model": "bedrock/anthropic.claude-sonnet-4-6",
            "harness_name": "appworld",
            "harness_commit": "pypi:appworld==0.1.3.post1;agents:a072b7a86e7c1d5b1d7175659d750ebb9b79f10a",
            "config": {"phase": args.phase, "dataset": args.dataset, "trial": args.trial},
            "cost_usd": 0,
        }
    )
    rows = []
    statuses: Counter[str] = Counter()
    for task_id in task_ids:
        task_dir = output_dir / "tasks" / task_id
        usage_path = task_dir / "misc" / "usage.json"
        usage = json.loads(usage_path.read_text()) if usage_path.exists() else {}
        task_eval = evaluation.get("individual", {}).get(task_id)
        status = "COMPLETE" if task_eval is not None else "ERROR"
        statuses[status] += 1
        passed = bool(task_eval and task_eval.get("success"))
        cost = usage_cost(usage)
        actual_route = route_map.get(task_id, "unknown")
        row = {
            "schema_version": 1,
            "run_id": args.run_id,
            "milestone": "M14",
            "vertical": "appworld",
            "phase": args.phase,
            "task_id": task_id,
            "trial": args.trial,
            "seed": 100,
            "status": status,
            "passed": passed,
            "reward": float(passed),
            "requested_model_route": "bedrock/us.anthropic.claude-sonnet-4-6",
            "actual_model_route": actual_route,
            "fallback_depth": int("global." in actual_route),
            "usage": usage,
            "cost_usd": cost,
            "evaluation": task_eval,
            "raw_output_prefix": str(task_dir),
        }
        rows.append(row)
        store.record_task_run(
            {
                **{key: row[key] for key in (
                    "run_id", "task_id", "trial", "seed", "status", "passed", "reward",
                    "requested_model_route", "actual_model_route", "fallback_depth", "usage", "cost_usd",
                )},
                "error": None if status == "COMPLETE" else {"reason": "missing evaluation"},
                "metadata": {"milestone": "M14", "vertical": "appworld", "phase": args.phase},
                "trace": row,
            }
        )
    total_cost = round(sum(row["cost_usd"] for row in rows), 6)
    store.record_run(
        {
            "run_id": args.run_id,
            "milestone": "M14",
            "vertical": "appworld",
            "status": "COMPLETE" if statuses.get("ERROR", 0) == 0 else "PAUSED",
            "subject_model": "bedrock/anthropic.claude-sonnet-4-6",
            "harness_name": "appworld",
            "harness_commit": "pypi:appworld==0.1.3.post1;agents:a072b7a86e7c1d5b1d7175659d750ebb9b79f10a",
            "config": {"phase": args.phase, "dataset": args.dataset, "trial": args.trial},
            "cost_usd": total_cost,
        }
    )
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    args.output_jsonl.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    summary = {
        "schema_version": 1,
        "run_id": args.run_id,
        "milestone": "M14",
        "vertical": "appworld",
        "phase": args.phase,
        "trial": args.trial,
        "rows": len(rows),
        "passes": sum(row["passed"] for row in rows),
        "pass_rate": sum(row["passed"] for row in rows) / len(rows) if rows else 0,
        "status_counts": dict(statuses),
        "cost_usd": total_cost,
        "models_seen": sorted({row["actual_model_route"] for row in rows}),
        "database_indexed": store.last_db_error is None,
    }
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))
    if statuses.get("ERROR"):
        raise SystemExit("AppWorld export found missing task evaluations")


if __name__ == "__main__":
    main()
