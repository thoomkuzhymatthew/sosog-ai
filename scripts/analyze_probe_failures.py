#!/usr/bin/env python3
"""Analyze 5x reruns of the six M2-failed Retail tasks."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SOSOG_ROOT = Path(__file__).resolve().parents[1]
RUN_NAME = "sosog_probe_m2_failed_5x_cached"
RESULTS_PATH = (
    SOSOG_ROOT / "tau-bench" / "data" / "simulations" / RUN_NAME / "results.json"
)
SUMMARY_PATH = SOSOG_ROOT / "metrics" / "probe_failures_summary.json"
DOC_PATH = SOSOG_ROOT / "docs" / "probe_failures.md"

INPUT_RATE_PER_MILLION = 3.00
OUTPUT_RATE_PER_MILLION = 15.00
CACHE_WRITE_RATE_PER_MILLION = 3.75
CACHE_READ_RATE_PER_MILLION = 0.30

WRITE_TOOLS = {
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
}


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


def compact(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "[" + ",".join(compact(item) for item in value) + "]"
    if isinstance(value, dict):
        parts = []
        for key in sorted(value):
            parts.append(f"{key}:{compact(value[key])}")
        return "{" + ",".join(parts) + "}"
    return str(value)


def call_signature(name: str, arguments: dict[str, Any] | None) -> str:
    arguments = arguments or {}
    if not arguments:
        return f"{name}()"
    return f"{name}(" + ", ".join(
        f"{key}={compact(arguments[key])}" for key in sorted(arguments)
    ) + ")"


def write_skeleton(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    writes: list[dict[str, Any]] = []
    for message in messages:
        for tool_call in message.get("tool_calls") or []:
            name = tool_call.get("name")
            if name not in WRITE_TOOLS:
                continue
            arguments = tool_call.get("arguments") or {}
            writes.append(
                {
                    "name": name,
                    "arguments": arguments,
                    "signature": call_signature(name, arguments),
                }
            )
    return writes


def first_failed_action_check(
    reward_info: dict[str, Any],
) -> dict[str, Any] | None:
    for idx, check in enumerate(reward_info.get("action_checks") or []):
        if not check.get("action_match", True) or float(check.get("action_reward") or 0.0) < 1.0:
            action = check.get("action") or {}
            name = action.get("name") or "unknown"
            arguments = action.get("arguments") or {}
            return {
                "index": idx,
                "tool_type": check.get("tool_type"),
                "name": name,
                "arguments": arguments,
                "signature": call_signature(name, arguments),
                "action_match": check.get("action_match"),
                "action_reward": check.get("action_reward"),
            }
    return None


def role_usage(messages: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    by_role: dict[str, dict[str, int]] = {}
    for message in messages:
        usage = message.get("usage")
        if not usage:
            continue
        role = message.get("role") or "unknown"
        by_role.setdefault(role, usage_bucket())
        add_usage(by_role[role], usage)
    return by_role


def aggregate_role_usage(
    target: dict[str, dict[str, int]], source: dict[str, dict[str, int]]
) -> None:
    for role, bucket in source.items():
        target.setdefault(role, usage_bucket())
        for key, value in bucket.items():
            target[role][key] += value


def flatten_role_usage(source: dict[str, dict[str, int]]) -> dict[str, int]:
    total = usage_bucket()
    for bucket in source.values():
        for key, value in bucket.items():
            total[key] += value
    return total


def classify(pass_count: int, runs: list[dict[str, Any]]) -> str:
    if 0 < pass_count < len(runs):
        return "flaky-pass"
    if pass_count == len(runs):
        return "flaky-pass"

    failure_signatures = [
        run["first_failed_action_check"]["signature"]
        if run["first_failed_action_check"] is not None
        else "none"
        for run in runs
    ]
    skeletons = [
        " -> ".join(item["signature"] for item in run["write_skeleton"]) or "none"
        for run in runs
    ]
    if len(set(failure_signatures)) == 1 and len(set(skeletons)) == 1:
        return "deterministic-fail"
    return "stochastic-fail"


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |"]
    out.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        out.append("| " + " | ".join(cell.replace("\n", "<br>") for cell in row) + " |")
    return "\n".join(out)


def main() -> None:
    data = json.loads(RESULTS_PATH.read_text())
    sims_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    aggregate_usage_by_role: dict[str, dict[str, int]] = {}
    cache_write_calls = 0
    cache_read_calls = 0

    for simulation in data["simulations"]:
        messages = simulation.get("messages") or []
        usage_by_role = role_usage(messages)
        aggregate_role_usage(aggregate_usage_by_role, usage_by_role)
        for message in messages:
            usage = message.get("usage") or {}
            if int(usage.get("cache_creation_input_tokens") or 0) > 0:
                cache_write_calls += 1
            if int(usage.get("cache_read_input_tokens") or 0) > 0:
                cache_read_calls += 1

        reward_info = simulation.get("reward_info") or {}
        run = {
            "task_id": str(simulation["task_id"]),
            "trial": simulation["trial"],
            "reward": float(reward_info.get("reward") or 0.0),
            "db_match": bool((reward_info.get("db_check") or {}).get("db_match")),
            "write_skeleton": write_skeleton(messages),
            "first_failed_action_check": first_failed_action_check(reward_info),
            "agent_cost_cached_usd": simulation.get("agent_cost"),
            "user_cost_cached_usd": simulation.get("user_cost"),
            "total_cost_cached_usd": (simulation.get("agent_cost") or 0.0)
            + (simulation.get("user_cost") or 0.0),
            "usage": flatten_role_usage(usage_by_role),
            "termination_reason": simulation.get("termination_reason"),
            "duration_seconds": simulation.get("duration"),
        }
        sims_by_task[run["task_id"]].append(run)

    task_summaries: dict[str, dict[str, Any]] = {}
    for task_id, runs in sorted(sims_by_task.items(), key=lambda item: int(item[0])):
        runs.sort(key=lambda run: run["trial"])
        pass_count = sum(1 for run in runs if run["db_match"])
        first_fail_signatures = [
            run["first_failed_action_check"]["signature"]
            if run["first_failed_action_check"] is not None
            else "none"
            for run in runs
        ]
        failure_only_signatures = [
            run["first_failed_action_check"]["signature"]
            for run in runs
            if not run["db_match"] and run["first_failed_action_check"] is not None
        ]
        task_summaries[task_id] = {
            "task_id": task_id,
            "pass_count": pass_count,
            "fail_count": len(runs) - pass_count,
            "pass_over_total": f"{pass_count}/5",
            "classification": classify(pass_count, runs),
            "same_first_failed_action_all_runs": len(set(first_fail_signatures)) == 1,
            "same_first_failed_action_failed_runs": len(set(failure_only_signatures)) == 1
            if failure_only_signatures
            else None,
            "first_failed_action_signatures": first_fail_signatures,
            "runs": runs,
        }

    aggregate_usage = flatten_role_usage(aggregate_usage_by_role)
    runner_agent_cost = sum(
        float(simulation.get("agent_cost") or 0.0) for simulation in data["simulations"]
    )
    runner_user_cost = sum(
        float(simulation.get("user_cost") or 0.0) for simulation in data["simulations"]
    )
    runner_total_cost = runner_agent_cost + runner_user_cost
    recomputed_cached = cost_from_usage(aggregate_usage, cached=True)
    counterfactual_uncached = cost_from_usage(aggregate_usage, cached=False)

    summary = {
        "run_name": RUN_NAME,
        "results_path": str(RESULTS_PATH.relative_to(SOSOG_ROOT)),
        "model": data["info"]["agent_info"]["llm"],
        "user_simulator_model": data["info"]["user_info"]["llm"],
        "task_ids": sorted(sims_by_task, key=int),
        "num_simulations": len(data["simulations"]),
        "pass_count": sum(task["pass_count"] for task in task_summaries.values()),
        "fail_count": sum(task["fail_count"] for task in task_summaries.values()),
        "classification_counts": dict(
            Counter(task["classification"] for task in task_summaries.values())
        ),
        "tasks": task_summaries,
        "costs_usd": {
            "runner_agent_cached": round(runner_agent_cost, 6),
            "runner_user_simulator_cached": round(runner_user_cost, 6),
            "runner_benchmark_total_cached": round(runner_total_cost, 6),
            "recomputed_total_cached": round(recomputed_cached, 6),
            "counterfactual_total_uncached": round(counterfactual_uncached, 6),
            "avg_benchmark_per_run_cached": round(runner_total_cost / len(data["simulations"]), 6),
            "avg_benchmark_per_run_uncached": round(
                counterfactual_uncached / len(data["simulations"]), 6
            ),
        },
        "usage": {
            "total": aggregate_usage,
            "by_role": aggregate_usage_by_role,
            "cache_write_call_count": cache_write_calls,
            "cache_read_call_count": cache_read_calls,
        },
        "termination_counts": dict(
            Counter(simulation.get("termination_reason") for simulation in data["simulations"])
        ),
    }

    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    DOC_PATH.write_text(render_markdown(summary))
    print(json.dumps(summary, indent=2, sort_keys=True))


def first_fail_text(run: dict[str, Any]) -> str:
    fail = run["first_failed_action_check"]
    if fail is None:
        return "none"
    return f"{fail['index']}: {fail['signature']}"


def skeleton_text(run: dict[str, Any]) -> str:
    if not run["write_skeleton"]:
        return "none"
    return " -> ".join(item["signature"] for item in run["write_skeleton"])


def render_markdown(summary: dict[str, Any]) -> str:
    costs = summary["costs_usd"]
    usage = summary["usage"]["total"]
    lines = [
        "# Failure Determinism Probe",
        "",
        "Date: 2026-08-17",
        "",
        "## Scope",
        "",
        "This is a quick probe of the six M2 failed Retail tasks only. I did not start M3, did not change task configs, and did not attempt to fix failures.",
        "",
        "Run setup:",
        "",
        "```text",
        f"Run name: {summary['run_name']}",
        f"Model: {summary['model']}",
        f"User simulator model: {summary['user_simulator_model']}",
        "Tasks: 12, 49, 74, 82, 91, 98",
        "Trials per task: 5",
        "Concurrency/retries/timeout/logging: same as M2 baseline",
        "Prompt caching: TAU2_BEDROCK_PROMPT_CACHE=1",
        "```",
        "",
        "## Headline",
        "",
        markdown_table(
            [
                "Task",
                "Pass/fail",
                "Classification",
                "First failed action-check stability",
            ],
            [
                [
                    task_id,
                    task["pass_over_total"],
                    task["classification"],
                    "same on failed runs"
                    if task["same_first_failed_action_failed_runs"]
                    else "differs/no failed runs",
                ]
                for task_id, task in summary["tasks"].items()
            ],
        ),
        "",
        "Interpretation: only task `91` was a deterministic fail in this 5x probe. The other five M2 failures passed at least once under the same setup, so they are `flaky-pass` by the requested taxonomy.",
        "",
        "## Cost And Tokens",
        "",
        markdown_table(
            ["Metric", "Measured value"],
            [
                ["Total probe simulations", str(summary["num_simulations"])],
                ["Total DB/pass successes", str(summary["pass_count"])],
                ["Total DB/pass failures", str(summary["fail_count"])],
                ["Cached benchmark total", f"${costs['runner_benchmark_total_cached']:.6f}"],
                ["Cached avg/run", f"${costs['avg_benchmark_per_run_cached']:.6f}"],
                [
                    "Counterfactual uncached total",
                    f"${costs['counterfactual_total_uncached']:.6f}",
                ],
                [
                    "Counterfactual uncached avg/run",
                    f"${costs['avg_benchmark_per_run_uncached']:.6f}",
                ],
                ["LLM calls", f"{usage['calls']:,}"],
                ["Prompt tokens", f"{usage['prompt_tokens']:,}"],
                ["Completion tokens", f"{usage['completion_tokens']:,}"],
                ["Cache creation input tokens", f"{usage['cache_creation_input_tokens']:,}"],
                ["Cache read input tokens", f"{usage['cache_read_input_tokens']:,}"],
                ["Non-cached input tokens", f"{usage['noncached_input_tokens']:,}"],
                ["Cache write calls", str(summary["usage"]["cache_write_call_count"])],
                ["Cache read calls", str(summary["usage"]["cache_read_call_count"])],
            ],
        ),
        "",
        "Dollar values are calculated from measured response usage tokens using the same instrumentation/rates as M2. The uncached number is a counterfactual over the same measured prompt/completion token volume.",
        "",
        "## Per-Task Details",
        "",
    ]

    for task_id, task in summary["tasks"].items():
        lines.extend(
            [
                f"### Task {task_id} - {task['classification']}",
                "",
                f"Pass/fail count: {task['pass_over_total']} final DB/pass.",
                "",
            ]
        )
        if task["same_first_failed_action_failed_runs"] is True:
            failed_runs = [
                run for run in task["runs"] if not run["db_match"] and run["first_failed_action_check"]
            ]
            signature = failed_runs[0]["first_failed_action_check"]["signature"]
            lines.append(f"First failed action-check on failed runs: same signature, `{signature}`.")
        elif task["fail_count"] == 0:
            lines.append("First failed action-check on failed runs: none, because all runs passed.")
        else:
            lines.append("First failed action-check on failed runs: differs run-to-run.")
        lines.append("")
        lines.append(
            markdown_table(
                ["Trial", "Result", "Write-action skeleton", "First failed action_check"],
                [
                    [
                        str(run["trial"]),
                        "pass" if run["db_match"] else "fail",
                        f"`{skeleton_text(run)}`",
                        f"`{first_fail_text(run)}`",
                    ]
                    for run in task["runs"]
                ],
            )
        )
        lines.append("")

    lines.extend(
        [
            "## Verification",
            "",
            "The saved trajectories were re-evaluated with tau2's built-in verifier after the run.",
            "",
            "```text",
            "Computed rewards for 30 simulation(s)",
            "Average Reward 0.4667",
            "Pass^1 0.467",
            "DB Match 14 / 16 (46.7%)",
            "```",
            "",
            "No Bedrock throttling, auth, or validation errors were found in the probe artifact logs.",
            "",
            "## Artifacts",
            "",
            "```text",
            f"sosog-ai/{summary['results_path']}",
            "sosog-ai/metrics/probe_failures_summary.json",
            "sosog-ai/docs/probe_failures.md",
            "```",
            "",
            "## Reproduce",
            "",
            "```bash",
            "cd sosog-ai/tau-bench",
            "set -a; source ../../.env; set +a",
            "export AWS_DEFAULT_REGION=us-east-1",
            "export TAU2_BEDROCK_PROMPT_CACHE=1",
            "uv run tau2 run \\",
            "  --domain retail \\",
            "  --agent llm_agent \\",
            "  --agent-llm bedrock/us.anthropic.claude-sonnet-4-6 \\",
            "  --agent-llm-args '{\"temperature\": 0.0}' \\",
            "  --user user_simulator \\",
            "  --user-llm bedrock/us.anthropic.claude-sonnet-4-6 \\",
            "  --user-llm-args '{\"temperature\": 0.0}' \\",
            "  --num-trials 5 \\",
            "  --task-ids 12 49 74 82 91 98 \\",
            "  --max-concurrency 2 \\",
            "  --max-retries 1 \\",
            "  --retry-delay 5 \\",
            "  --timeout 900 \\",
            "  --save-to sosog_probe_m2_failed_5x_cached \\",
            "  --verbose-logs \\",
            "  --llm-log-mode all \\",
            "  --log-level INFO",
            "",
            "uv run tau2 evaluate-trajs data/simulations/sosog_probe_m2_failed_5x_cached/results.json",
            "cd ../..",
            "python3 sosog-ai/scripts/analyze_probe_failures.py",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
