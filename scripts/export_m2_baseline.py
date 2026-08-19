#!/usr/bin/env python3
"""Export the M2 tau2 baseline as summary metrics and JSONL traces."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


SOSOG_ROOT = Path(__file__).resolve().parents[1]
RUN_NAME = "sosog_m2_retail_db_checkable_cached_baseline"
RESULTS_PATH = (
    SOSOG_ROOT
    / "tau-bench"
    / "data"
    / "simulations"
    / RUN_NAME
    / "results.json"
)
FILTER_PATH = SOSOG_ROOT / "config" / "retail_db_checkable_task_ids.json"
SUMMARY_PATH = SOSOG_ROOT / "metrics" / "m2_baseline_summary.json"
PER_TASK_CSV_PATH = SOSOG_ROOT / "metrics" / "m2_per_task_costs.csv"
TRACES_PATH = SOSOG_ROOT / "traces" / "m2" / "retail_db_checkable_baseline.jsonl"

INPUT_RATE_PER_MILLION = 3.00
OUTPUT_RATE_PER_MILLION = 15.00
CACHE_WRITE_RATE_PER_MILLION = 3.75
CACHE_READ_RATE_PER_MILLION = 0.30


def usage_bucket() -> dict[str, int]:
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "noncached_input_tokens": 0,
    }


def add_usage(bucket: dict[str, int], usage: dict[str, Any]) -> None:
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    cache_creation_tokens = int(usage.get("cache_creation_input_tokens") or 0)
    cache_read_tokens = int(usage.get("cache_read_input_tokens") or 0)
    noncached_tokens = max(0, prompt_tokens - cache_creation_tokens - cache_read_tokens)

    bucket["calls"] += 1
    bucket["prompt_tokens"] += prompt_tokens
    bucket["completion_tokens"] += completion_tokens
    bucket["total_tokens"] += int(
        usage.get("total_tokens") or (prompt_tokens + completion_tokens)
    )
    bucket["cache_creation_input_tokens"] += cache_creation_tokens
    bucket["cache_read_input_tokens"] += cache_read_tokens
    bucket["noncached_input_tokens"] += noncached_tokens


def cost_from_usage(bucket: dict[str, int], *, cached: bool) -> float:
    if cached:
        input_cost = (
            bucket["noncached_input_tokens"] * INPUT_RATE_PER_MILLION
            + bucket["cache_creation_input_tokens"] * CACHE_WRITE_RATE_PER_MILLION
            + bucket["cache_read_input_tokens"] * CACHE_READ_RATE_PER_MILLION
        )
    else:
        input_cost = bucket["prompt_tokens"] * INPUT_RATE_PER_MILLION

    output_cost = bucket["completion_tokens"] * OUTPUT_RATE_PER_MILLION
    return (input_cost + output_cost) / 1_000_000


def round_cost(value: float) -> float:
    return round(value, 6)


def action_sequence(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sequence: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        for tool_call in message.get("tool_calls") or []:
            item = {
                "turn_idx": message.get("turn_idx"),
                "call_id": tool_call.get("id"),
                "name": tool_call.get("name"),
                "arguments": tool_call.get("arguments"),
                "result": None,
            }
            sequence.append(item)
            pending.append(item)
        if role == "tool":
            target = pending.pop(0) if pending else None
            if target is not None:
                target["result"] = message.get("content")
    return sequence


def role_usage_for_messages(messages: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    role_usage: dict[str, dict[str, int]] = {}
    for message in messages:
        usage = message.get("usage")
        if not usage:
            continue
        role = message.get("role") or "unknown"
        role_usage.setdefault(role, usage_bucket())
        add_usage(role_usage[role], usage)
    return role_usage


def flatten_role_usage(role_usage: dict[str, dict[str, int]]) -> dict[str, int]:
    total = usage_bucket()
    for bucket in role_usage.values():
        for key, value in bucket.items():
            total[key] += value
    return total


def main() -> None:
    data = json.loads(RESULTS_PATH.read_text())
    filter_data = json.loads(FILTER_PATH.read_text())
    tasks_by_id = {str(task["id"]): task for task in data["tasks"]}
    simulations = data["simulations"]

    per_task_rows: list[dict[str, Any]] = []
    aggregate_usage = usage_bucket()
    aggregate_usage_by_role: dict[str, dict[str, int]] = {}
    termination_counts: Counter[str] = Counter()
    failed_task_ids: list[str] = []
    db_pass_count = 0
    reward_sum = 0.0
    action_totals: Counter[str] = Counter()
    action_passes: Counter[str] = Counter()
    no_nl_assertions_count = 0
    traces: list[dict[str, Any]] = []

    for simulation in simulations:
        task_id = str(simulation["task_id"])
        messages = simulation.get("messages") or []
        role_usage = role_usage_for_messages(messages)
        total_usage = flatten_role_usage(role_usage)

        for key, value in total_usage.items():
            aggregate_usage[key] += value
        for role, bucket in role_usage.items():
            aggregate_usage_by_role.setdefault(role, usage_bucket())
            for key, value in bucket.items():
                aggregate_usage_by_role[role][key] += value

        reward_info = simulation.get("reward_info") or {}
        reward = float(reward_info.get("reward") or 0.0)
        db_check = reward_info.get("db_check") or {}
        db_match = bool(db_check.get("db_match"))
        reward_sum += reward
        if db_match:
            db_pass_count += 1
        else:
            failed_task_ids.append(task_id)

        if not reward_info.get("nl_assertions"):
            no_nl_assertions_count += 1

        for action_check in reward_info.get("action_checks") or []:
            tool_type = action_check.get("tool_type") or "unknown"
            action_totals[tool_type] += 1
            if float(action_check.get("action_reward") or 0.0) >= 1.0:
                action_passes[tool_type] += 1

        termination_counts[simulation.get("termination_reason") or "unknown"] += 1

        cached_cost = cost_from_usage(total_usage, cached=True)
        uncached_cost = cost_from_usage(total_usage, cached=False)
        sim_record = {
            "task_id": task_id,
            "trial": simulation.get("trial"),
            "simulation_id": simulation.get("id"),
            "reward": reward,
            "db_match": db_match,
            "agent_cost_cached_usd": simulation.get("agent_cost"),
            "user_cost_cached_usd": simulation.get("user_cost"),
            "total_cost_cached_usd": simulation.get("agent_cost", 0.0)
            + simulation.get("user_cost", 0.0),
            "recomputed_total_cost_cached_usd": cached_cost,
            "counterfactual_total_cost_uncached_usd": uncached_cost,
            "usage": total_usage,
            "duration_seconds": simulation.get("duration"),
            "termination_reason": simulation.get("termination_reason"),
            "messages_count": len(messages),
            "actions_count": len(action_sequence(messages)),
        }
        per_task_rows.append(sim_record)

        traces.append(
            {
                "milestone": "M2",
                "run_name": RUN_NAME,
                "task": tasks_by_id.get(task_id),
                "simulation": {
                    "id": simulation.get("id"),
                    "task_id": task_id,
                    "trial": simulation.get("trial"),
                    "seed": simulation.get("seed"),
                    "start_time": simulation.get("start_time"),
                    "end_time": simulation.get("end_time"),
                    "duration_seconds": simulation.get("duration"),
                    "termination_reason": simulation.get("termination_reason"),
                    "mode": simulation.get("mode"),
                },
                "reward_info": reward_info,
                "costs": {
                    "agent_cached_usd": simulation.get("agent_cost"),
                    "user_cached_usd": simulation.get("user_cost"),
                    "total_cached_usd": simulation.get("agent_cost", 0.0)
                    + simulation.get("user_cost", 0.0),
                    "recomputed_total_cached_usd": cached_cost,
                    "counterfactual_total_uncached_usd": uncached_cost,
                    "rates_per_million_tokens": {
                        "input": INPUT_RATE_PER_MILLION,
                        "output": OUTPUT_RATE_PER_MILLION,
                        "cache_write": CACHE_WRITE_RATE_PER_MILLION,
                        "cache_read": CACHE_READ_RATE_PER_MILLION,
                    },
                },
                "usage": {
                    "total": total_usage,
                    "by_role": role_usage,
                },
                "action_sequence": action_sequence(messages),
                "messages": messages,
            }
        )

    sim_count = len(simulations)
    runner_total_cost = sum(
        row["total_cost_cached_usd"] for row in per_task_rows
    )
    runner_agent_cost = sum(
        float(simulation.get("agent_cost") or 0.0) for simulation in simulations
    )
    runner_user_cost = sum(
        float(simulation.get("user_cost") or 0.0) for simulation in simulations
    )
    recomputed_cached_cost = cost_from_usage(aggregate_usage, cached=True)
    uncached_cost = cost_from_usage(aggregate_usage, cached=False)
    role_costs = {
        role: {
            "cached": round_cost(cost_from_usage(bucket, cached=True)),
            "counterfactual_uncached": round_cost(
                cost_from_usage(bucket, cached=False)
            ),
        }
        for role, bucket in sorted(aggregate_usage_by_role.items())
    }

    summary = {
        "run_name": RUN_NAME,
        "results_path": str(RESULTS_PATH.relative_to(SOSOG_ROOT)),
        "trace_jsonl_path": str(TRACES_PATH.relative_to(SOSOG_ROOT)),
        "per_task_csv_path": str(PER_TASK_CSV_PATH.relative_to(SOSOG_ROOT)),
        "filter": {
            "path": str(FILTER_PATH.relative_to(SOSOG_ROOT)),
            "definition": filter_data["filter"],
            "total_retail_tasks": filter_data["total_retail_tasks"],
            "kept_count": filter_data["kept_count"],
            "excluded_count": filter_data["excluded_count"],
            "excluded_non_empty_nl_assertion_count": filter_data[
                "excluded_non_empty_nl_assertion_count"
            ],
            "excluded_non_db_count": filter_data["excluded_non_db_count"],
            "kept_task_ids": filter_data["kept_task_ids"],
            "excluded_non_empty_nl_assertion_task_ids": filter_data[
                "excluded_non_empty_nl_assertion_task_ids"
            ],
        },
        "model": data["info"]["agent_info"]["llm"],
        "user_simulator_model": data["info"]["user_info"]["llm"],
        "tau2_commit": data["info"]["git_commit"],
        "num_simulations": sim_count,
        "num_tasks": len({simulation["task_id"] for simulation in simulations}),
        "pass_count": db_pass_count,
        "fail_count": sim_count - db_pass_count,
        "pass_rate": round(db_pass_count / sim_count, 6),
        "average_reward": round(reward_sum / sim_count, 6),
        "failed_task_ids": failed_task_ids,
        "termination_counts": dict(termination_counts),
        "no_nl_assertions_count": no_nl_assertions_count,
        "llm_judge_tasks_excluded": filter_data[
            "excluded_non_empty_nl_assertion_count"
        ],
        "costs_usd": {
            "runner_agent_cached": round_cost(runner_agent_cost),
            "runner_user_simulator_cached": round_cost(runner_user_cost),
            "runner_benchmark_total_cached": round_cost(runner_total_cost),
            "recomputed_total_cached": round_cost(recomputed_cached_cost),
            "counterfactual_total_uncached": round_cost(uncached_cost),
            "avg_agent_per_task_cached": round_cost(runner_agent_cost / sim_count),
            "avg_user_simulator_per_task_cached": round_cost(
                runner_user_cost / sim_count
            ),
            "avg_benchmark_per_task_cached": round_cost(runner_total_cost / sim_count),
            "avg_benchmark_per_task_uncached": round_cost(uncached_cost / sim_count),
            "savings_vs_uncached": round_cost(uncached_cost - runner_total_cost),
            "savings_percent_vs_uncached": round(
                ((uncached_cost - runner_total_cost) / uncached_cost) * 100, 2
            ),
            "by_role": role_costs,
        },
        "usage": {
            "total": aggregate_usage,
            "by_role": aggregate_usage_by_role,
            "cache_read_call_count": sum(
                1
                for simulation in simulations
                for message in simulation.get("messages") or []
                if (message.get("usage") or {}).get("cache_read_input_tokens", 0)
                > 0
            ),
            "cache_write_call_count": sum(
                1
                for simulation in simulations
                for message in simulation.get("messages") or []
                if (message.get("usage") or {}).get("cache_creation_input_tokens", 0)
                > 0
            ),
        },
        "action_metrics": {
            tool_type: {
                "passed": action_passes[tool_type],
                "total": action_totals[tool_type],
                "pass_rate": round(action_passes[tool_type] / action_totals[tool_type], 6)
                if action_totals[tool_type]
                else None,
            }
            for tool_type in sorted(action_totals)
        },
        "cost_basis": {
            "currency": "USD",
            "rates_per_million_tokens": {
                "input": INPUT_RATE_PER_MILLION,
                "output": OUTPUT_RATE_PER_MILLION,
                "cache_write": CACHE_WRITE_RATE_PER_MILLION,
                "cache_read": CACHE_READ_RATE_PER_MILLION,
            },
            "note": (
                "Dollar values are calculated from measured response usage tokens "
                "and the rates above; uncached values are a counterfactual using "
                "the same prompt/completion tokens with no cache write/read split."
            ),
        },
    }

    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    with PER_TASK_CSV_PATH.open("w", newline="") as csvfile:
        fieldnames = [
            "task_id",
            "trial",
            "reward",
            "db_match",
            "total_cost_cached_usd",
            "counterfactual_total_cost_uncached_usd",
            "prompt_tokens",
            "completion_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "noncached_input_tokens",
            "duration_seconds",
            "termination_reason",
            "messages_count",
            "actions_count",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in per_task_rows:
            writer.writerow(
                {
                    "task_id": row["task_id"],
                    "trial": row["trial"],
                    "reward": row["reward"],
                    "db_match": row["db_match"],
                    "total_cost_cached_usd": round_cost(
                        row["total_cost_cached_usd"]
                    ),
                    "counterfactual_total_cost_uncached_usd": round_cost(
                        row["counterfactual_total_cost_uncached_usd"]
                    ),
                    "prompt_tokens": row["usage"]["prompt_tokens"],
                    "completion_tokens": row["usage"]["completion_tokens"],
                    "cache_creation_input_tokens": row["usage"][
                        "cache_creation_input_tokens"
                    ],
                    "cache_read_input_tokens": row["usage"][
                        "cache_read_input_tokens"
                    ],
                    "noncached_input_tokens": row["usage"][
                        "noncached_input_tokens"
                    ],
                    "duration_seconds": round(row["duration_seconds"], 3),
                    "termination_reason": row["termination_reason"],
                    "messages_count": row["messages_count"],
                    "actions_count": row["actions_count"],
                }
            )
    with TRACES_PATH.open("w") as trace_file:
        for trace in traces:
            trace_file.write(json.dumps(trace, sort_keys=True) + "\n")

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
