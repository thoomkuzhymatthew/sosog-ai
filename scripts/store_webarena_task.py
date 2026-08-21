#!/usr/bin/env python3
"""Persist one canonical WebArena task result immediately after evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_ops.persistence import ResearchStore, StoreConfig  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--trial", type=int, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--usage-log", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    log = args.log.read_text(errors="replace") if args.log.exists() else ""
    usage_rows = []
    if args.usage_log.exists():
        for line in args.usage_log.read_text().splitlines():
            row = json.loads(line)
            if str(row.get("task_id")) == args.task_id:
                usage_rows.append(row)
    passed = "[Result] (PASS)" in log
    completed = passed or "[Result] (FAIL)" in log
    routes = [row["model"] for row in usage_rows]
    actual_route = next((route for route in routes if "global." in route), routes[-1] if routes else "unknown")
    usage = {
        "calls": len(usage_rows),
        "prompt_tokens": sum(int(row.get("usage", {}).get("prompt_tokens") or 0) for row in usage_rows),
        "completion_tokens": sum(int(row.get("usage", {}).get("completion_tokens") or 0) for row in usage_rows),
    }
    cost = round(sum(float(row.get("cost_usd") or 0) for row in usage_rows), 6)
    row = {
        "schema_version": 1,
        "run_id": args.run_id,
        "milestone": "M16",
        "vertical": "webarena",
        "phase": args.phase,
        "task_id": args.task_id,
        "trial": args.trial,
        "seed": 42,
        "status": "COMPLETE" if completed else "ERROR",
        "passed": passed,
        "reward": float(passed),
        "requested_model_route": "bedrock/us.anthropic.claude-sonnet-4-6",
        "actual_model_route": actual_route,
        "fallback_depth": int("global." in actual_route),
        "usage": usage,
        "cost_usd": cost,
        "models_seen": sorted(set(routes)),
        "raw_result_dir": str(args.result_dir),
    }
    store = ResearchStore(StoreConfig.from_env())
    store.record_run(
        {
            "run_id": args.run_id,
            "milestone": "M16",
            "vertical": "webarena",
            "status": "RUNNING",
            "subject_model": "bedrock/anthropic.claude-sonnet-4-6",
            "harness_name": "webarena",
            "harness_commit": "dce04686a56253aefba7b18a4fa0937cf1dc987b",
            "config": {"phase": args.phase, "trial": args.trial},
            "cost_usd": 0,
        }
    )
    store.record_task_run(
        {
            **{key: row[key] for key in (
                "run_id", "task_id", "trial", "seed", "status", "passed", "reward",
                "requested_model_route", "actual_model_route", "fallback_depth", "usage", "cost_usd",
            )},
            "error": None if completed else {"reason": "runner did not emit an evaluation result"},
            "metadata": {"milestone": "M16", "vertical": "webarena", "phase": args.phase},
            "trace": row,
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    print(json.dumps(row, sort_keys=True))


if __name__ == "__main__":
    main()
