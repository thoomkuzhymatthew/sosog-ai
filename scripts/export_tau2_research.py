#!/usr/bin/env python3
"""Normalize a tau2 checkpoint into research JSONL, S3 rows, and RDS metadata."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_ops.persistence import ResearchStore, StoreConfig  # noqa: E402


def usage_bucket() -> dict[str, int]:
    return {
        "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "total_tokens": 0, "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0, "noncached_input_tokens": 0,
    }


def usage_for(messages: list[dict[str, Any]]) -> dict[str, int]:
    total = usage_bucket()
    for message in messages:
        usage = message.get("usage") or {}
        if not usage:
            continue
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        cache_write = int(usage.get("cache_creation_input_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or 0)
        total["calls"] += 1
        total["prompt_tokens"] += prompt
        total["completion_tokens"] += completion
        total["total_tokens"] += int(usage.get("total_tokens") or prompt + completion)
        total["cache_creation_input_tokens"] += cache_write
        total["cache_read_input_tokens"] += cache_read
        total["noncached_input_tokens"] += max(0, prompt - cache_write - cache_read)
    return total


def cost_for(usage: dict[str, int]) -> float:
    value = (
        usage["noncached_input_tokens"] * 3.00
        + usage["cache_creation_input_tokens"] * 3.75
        + usage["cache_read_input_tokens"] * 0.30
        + usage["completion_tokens"] * 15.00
    ) / 1_000_000
    return round(value, 6)


def key_for(item: dict[str, Any]) -> str:
    return f"{item.get('task_id')}:{item.get('trial', 0)}:{item.get('seed', 0)}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--milestone", required=True)
    parser.add_argument("--vertical", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--harness-commit", required=True)
    parser.add_argument("--route-map", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--no-remote", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.results.read_text())
    route_map = json.loads(args.route_map.read_text())
    tasks = {str(item["id"]): item for item in data.get("tasks", [])}
    default_route = data.get("info", {}).get("agent_info", {}).get("llm", "unknown")
    traces = []
    costs = []
    statuses: Counter[str] = Counter()
    store = None if args.no_remote else ResearchStore(StoreConfig.from_env())

    for simulation in data.get("simulations", []):
        task_id = str(simulation["task_id"])
        messages = simulation.get("messages") or []
        usage = usage_for(messages)
        cost = cost_for(usage)
        reward_info = simulation.get("reward_info") or {}
        reward = float(reward_info.get("reward") or 0)
        status = (
            "ERROR"
            if simulation.get("termination_reason") == "infrastructure_error"
            else "COMPLETE"
        )
        statuses[status] += 1
        actual_route = route_map.get(key_for(simulation), default_route)
        trace = {
            "schema_version": 1,
            "milestone": args.milestone,
            "vertical": args.vertical,
            "phase": args.phase,
            "run_id": args.run_id,
            "task_id": task_id,
            "trial": int(simulation.get("trial") or 0),
            "seed": int(simulation.get("seed") or 0),
            "status": status,
            "passed": reward >= 1.0,
            "reward": reward,
            "requested_model_route": "bedrock/us.anthropic.claude-sonnet-4-6",
            "actual_model_route": actual_route,
            "fallback_depth": int("global." in actual_route),
            "usage": usage,
            "cost_usd": cost,
            "termination_reason": simulation.get("termination_reason"),
            "task": tasks.get(task_id),
            "reward_info": reward_info,
            "messages": messages,
            "simulation": {
                key: simulation.get(key)
                for key in ("id", "start_time", "end_time", "duration", "mode")
            },
        }
        traces.append(trace)
        costs.append(cost)
        if store is not None:
            store.record_task_run(
                {
                    **{key: trace[key] for key in (
                        "run_id", "task_id", "trial", "seed", "status", "passed",
                        "reward", "requested_model_route", "actual_model_route",
                        "fallback_depth", "usage", "cost_usd",
                    )},
                    "error": (
                        {"termination_reason": simulation.get("termination_reason")}
                        if status == "ERROR" else None
                    ),
                    "metadata": {
                        "milestone": args.milestone,
                        "vertical": args.vertical,
                        "phase": args.phase,
                    },
                    "trace": trace,
                    "started_at": simulation.get("start_time"),
                    "completed_at": simulation.get("end_time"),
                }
            )

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    args.output_jsonl.write_text(
        "".join(json.dumps(item, sort_keys=True, default=str) + "\n" for item in traces)
    )
    summary = {
        "schema_version": 1,
        "run_id": args.run_id,
        "milestone": args.milestone,
        "vertical": args.vertical,
        "phase": args.phase,
        "harness_commit": args.harness_commit,
        "rows": len(traces),
        "status_counts": dict(statuses),
        "passes": sum(item["passed"] for item in traces),
        "pass_rate": sum(item["passed"] for item in traces) / len(traces) if traces else 0,
        "cost_usd": round(sum(costs), 6),
        "models_seen": sorted({item["actual_model_route"] for item in traces}),
        "results_path": str(args.results),
        "trace_path": str(args.output_jsonl),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    if summary["cost_usd"] > float(os.environ.get("SOSOG_TRACK_BUDGET_USD", "inf")):
        raise SystemExit(f"track budget exceeded: ${summary['cost_usd']}")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
