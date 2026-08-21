#!/usr/bin/env python3
"""Normalize one evaluated SWE Verified slice into S3 and PostgreSQL rows."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_ops.persistence import ResearchStore, StoreConfig  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--route-map", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--trial", type=int, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.report.read_text())
    routes = json.loads(args.route_map.read_text())
    resolved = set(report.get("resolved_ids", []))
    completed = set(report.get("completed_ids", []))
    errors = set(report.get("error_ids", []))
    task_ids = sorted(set(report.get("submitted_ids", [])))
    store = ResearchStore(StoreConfig.from_env())
    harness_commit = "7a21e05772954cc81471ae19d56f436cecf43c54"
    store.record_run(
        {
            "run_id": args.run_id,
            "milestone": "M15",
            "vertical": "swe_verified",
            "status": "RUNNING",
            "subject_model": "bedrock/anthropic.claude-sonnet-4-6",
            "harness_name": "SWE-bench",
            "harness_commit": harness_commit,
            "config": {"phase": args.phase, "trial": args.trial},
            "cost_usd": 0,
        }
    )
    rows = []
    statuses: Counter[str] = Counter()
    for task_id in task_ids:
        trajectory_path = args.output_dir / task_id / f"{task_id}.traj.json"
        trajectory = json.loads(trajectory_path.read_text()) if trajectory_path.exists() else {}
        info = trajectory.get("info", {})
        status = "ERROR" if task_id in errors or task_id not in completed else "COMPLETE"
        statuses[status] += 1
        cost = round(float(info.get("model_stats", {}).get("instance_cost") or 0), 6)
        actual_route = routes.get(task_id, info.get("config", {}).get("model", {}).get("model_name", "unknown"))
        row = {
            "schema_version": 1,
            "run_id": args.run_id,
            "milestone": "M15",
            "vertical": "swe_verified",
            "phase": args.phase,
            "task_id": task_id,
            "trial": args.trial,
            "seed": 42,
            "status": status,
            "passed": task_id in resolved,
            "reward": float(task_id in resolved),
            "requested_model_route": "bedrock/us.anthropic.claude-sonnet-4-6",
            "actual_model_route": actual_route,
            "fallback_depth": int("global." in actual_route),
            "usage": info.get("model_stats", {}),
            "cost_usd": cost,
            "exit_status": info.get("exit_status"),
            "evaluation": {
                "resolved": task_id in resolved,
                "completed": task_id in completed,
                "infrastructure_failure": task_id in set(report.get("infra_failure_ids", [])),
            },
            "raw_trajectory": str(trajectory_path),
        }
        rows.append(row)
        store.record_task_run(
            {
                **{key: row[key] for key in (
                    "run_id", "task_id", "trial", "seed", "status", "passed", "reward",
                    "requested_model_route", "actual_model_route", "fallback_depth", "usage", "cost_usd",
                )},
                "error": None if status == "COMPLETE" else {"exit_status": info.get("exit_status")},
                "metadata": {"milestone": "M15", "vertical": "swe_verified", "phase": args.phase},
                "trace": row,
            }
        )
    total_cost = round(sum(row["cost_usd"] for row in rows), 6)
    store.record_run(
        {
            "run_id": args.run_id,
            "milestone": "M15",
            "vertical": "swe_verified",
            "status": "COMPLETE" if not statuses.get("ERROR") else "PAUSED",
            "subject_model": "bedrock/anthropic.claude-sonnet-4-6",
            "harness_name": "SWE-bench",
            "harness_commit": harness_commit,
            "config": {"phase": args.phase, "trial": args.trial},
            "cost_usd": total_cost,
        }
    )
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    args.output_jsonl.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    summary = {
        "schema_version": 1,
        "run_id": args.run_id,
        "milestone": "M15",
        "vertical": "swe_verified",
        "phase": args.phase,
        "trial": args.trial,
        "rows": len(rows),
        "passes": len(resolved & set(task_ids)),
        "pass_rate": len(resolved & set(task_ids)) / len(task_ids) if task_ids else 0,
        "status_counts": dict(statuses),
        "cost_usd": total_cost,
        "models_seen": sorted({row["actual_model_route"] for row in rows}),
        "database_indexed": store.last_db_error is None,
    }
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
