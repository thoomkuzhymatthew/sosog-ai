#!/usr/bin/env python3
"""M12 exemplar-lifting harness.

Runs matched baseline vs lifted-agent samples for selected flaky lift
candidates. The lifted agent receives 1-2 successful M3 write traces as
guidance in its system prompt, but must still verify current tool outputs and
obtain normal user confirmation before writing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger

logger.remove()

from tau2.agent.llm_agent import (  # noqa: E402
    AGENT_INSTRUCTION,
    SYSTEM_PROMPT,
    LLMAgent,
    LLMAgentState,
)
from tau2.data_model.message import Message, SystemMessage  # noqa: E402
from tau2.data_model.simulation import TextRunConfig  # noqa: E402
from tau2.domains.retail.environment import get_tasks  # noqa: E402
from tau2.evaluator.evaluator import EvaluationType  # noqa: E402
from tau2.registry import registry  # noqa: E402
from tau2.runner.build import build_text_orchestrator  # noqa: E402
from tau2.runner.simulation import run_simulation  # noqa: E402


SOSOG_ROOT = Path(__file__).resolve().parents[1]
M3_JSONL = SOSOG_ROOT / "traces" / "m3" / "retail_db_checkable_n10_final_valid.jsonl"
OUT_JSON = SOSOG_ROOT / "metrics" / "m12_lifting_results.json"
OUT_JSONL = SOSOG_ROOT / "traces" / "m12" / "lifting_probe.jsonl"
DEFAULT_MODEL = "bedrock/global.anthropic.claude-sonnet-4-6"
MODEL = os.environ.get("M12_MODEL", DEFAULT_MODEL)

DEFAULT_TASKS = ["49", "96"]
SEEDS = [
    1204901,
    1204919,
    1204937,
    1204961,
    1204979,
    1204991,
    1205023,
    1205053,
    1205081,
    1205113,
    1205141,
    1205167,
    1205203,
    1205237,
    1205261,
    1205297,
    1205321,
    1205351,
    1205377,
    1205411,
]

WRITE_TOOLS = {
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
}

CURRENT_TASK_ID = ""
EXEMPLARS_BY_TASK: dict[str, str] = {}


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


def add_usage(bucket: dict[str, int], usage: dict[str, Any] | None) -> None:
    if not usage:
        return
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    cache_creation_tokens = int(usage.get("cache_creation_input_tokens") or 0)
    cache_read_tokens = int(usage.get("cache_read_input_tokens") or 0)
    bucket["calls"] += 1
    bucket["prompt_tokens"] += prompt_tokens
    bucket["completion_tokens"] += completion_tokens
    bucket["total_tokens"] += int(
        usage.get("total_tokens") or prompt_tokens + completion_tokens
    )
    bucket["cache_creation_input_tokens"] += cache_creation_tokens
    bucket["cache_read_input_tokens"] += cache_read_tokens
    bucket["noncached_input_tokens"] += max(
        0, prompt_tokens - cache_creation_tokens - cache_read_tokens
    )


def role_usage_for_messages(messages: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    by_role: dict[str, dict[str, int]] = {}
    for message in messages:
        usage = message.get("usage")
        if not usage:
            continue
        role = message.get("role") or "unknown"
        by_role.setdefault(role, usage_bucket())
        add_usage(by_role[role], usage)
    return by_role


def flatten_usage(by_role: dict[str, dict[str, int]]) -> dict[str, int]:
    total = usage_bucket()
    for bucket in by_role.values():
        for key, value in bucket.items():
            total[key] += int(value or 0)
    return total


def cost_from_usage(bucket: dict[str, int]) -> float:
    input_rate = 3.00
    output_rate = 15.00
    cache_write_rate = 3.75
    cache_read_rate = 0.30
    input_cost = (
        bucket["noncached_input_tokens"] * input_rate
        + bucket["cache_creation_input_tokens"] * cache_write_rate
        + bucket["cache_read_input_tokens"] * cache_read_rate
    )
    return (input_cost + bucket["completion_tokens"] * output_rate) / 1_000_000


def call_signature(name: str, arguments: dict[str, Any] | None) -> str:
    return f"{name}({json.dumps(arguments or {}, sort_keys=True, separators=(',', ':'))})"


def write_skeleton(messages: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for message in messages:
        for tool_call in message.get("tool_calls") or []:
            if tool_call.get("name") in WRITE_TOOLS:
                out.append(
                    call_signature(tool_call["name"], tool_call.get("arguments") or {})
                )
    return out


def compact_json_observation(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    if "order_id" in value:
        return {
            "order_id": value.get("order_id"),
            "status": value.get("status"),
            "items": [
                {
                    "name": item.get("name"),
                    "product_id": item.get("product_id"),
                    "item_id": item.get("item_id"),
                    "price": item.get("price"),
                    "options": item.get("options"),
                }
                for item in value.get("items", [])
            ],
            "payment_method_ids": [
                payment.get("payment_method_id")
                for payment in value.get("payment_history", [])
            ],
            "exchange_items": value.get("exchange_items"),
            "exchange_new_items": value.get("exchange_new_items"),
            "return_items": value.get("return_items"),
            "cancel_reason": value.get("cancel_reason"),
        }

    if "variants" in value:
        variants = value.get("variants") or {}
        return {
            "name": value.get("name"),
            "product_id": value.get("product_id"),
            "variants": [
                {
                    "item_id": variant.get("item_id"),
                    "available": variant.get("available"),
                    "price": variant.get("price"),
                    "options": variant.get("options"),
                }
                for variant in variants.values()
            ],
        }

    if "user_id" in value and "orders" in value:
        return {
            "user_id": value.get("user_id"),
            "name": value.get("name"),
            "zip": ((value.get("address") or {}).get("zip")),
            "payment_method_ids": list((value.get("payment_methods") or {}).keys()),
            "orders": value.get("orders"),
        }

    return value


def compact_tool_observation(content: str, max_chars: int = 1800) -> str:
    try:
        parsed = json.loads(content)
    except Exception:
        return content[:max_chars]
    compact = compact_json_observation(parsed)
    return json.dumps(compact, sort_keys=True, separators=(",", ":"))[:max_chars]


def compact_success_trace(row: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    messages = row.get("messages") or []
    last_write_seen = False
    include_next_tool = False
    for message in messages:
        role = message.get("role")
        if role == "user" and message.get("content"):
            lines.append(f"USER: {str(message['content'])[:300]}")
        for tool_call in message.get("tool_calls") or []:
            signature = call_signature(tool_call["name"], tool_call.get("arguments") or {})
            prefix = "WRITE" if tool_call["name"] in WRITE_TOOLS else "READ"
            lines.append(f"{prefix}: {signature}")
            if tool_call["name"] in WRITE_TOOLS:
                last_write_seen = True
                include_next_tool = True
        if role == "tool" and message.get("content"):
            lines.append(f"OBSERVE: {compact_tool_observation(str(message['content']))}")
            if include_next_tool:
                break
        if last_write_seen and not include_next_tool:
            break
    return lines


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out.pop("messages", None)
    return out


def resume_key(row: dict[str, Any]) -> tuple[str, str, int] | None:
    task_id = row.get("task_id")
    arm = row.get("arm")
    trial = row.get("trial")
    if task_id is None or arm not in {"baseline", "lifted"} or trial is None:
        return None
    return (str(task_id), str(arm), int(trial))


def load_existing_rows(
    path: Path, task_ids: list[str], n: int, *, ok_only: bool
) -> tuple[list[dict[str, Any]], set[tuple[str, str, int]]]:
    if not path.exists():
        return [], set()

    wanted_tasks = {str(task_id) for task_id in task_ids}
    by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    with path.open() as jsonl:
        for line in jsonl:
            if not line.strip():
                continue
            row = json.loads(line)
            key = resume_key(row)
            if key is None:
                continue
            task_id, _arm, trial = key
            if task_id not in wanted_tasks or trial >= n:
                continue
            if ok_only and row.get("status") != "ok":
                continue
            by_key[key] = row

    rows = sorted(by_key.values(), key=lambda row: (row["trial"], row["task_id"], row["arm"]))
    return rows, set(by_key)


def load_m3_rows(task_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    wanted = {str(task_id) for task_id in task_ids}
    rows_by_task = {task_id: [] for task_id in wanted}
    with M3_JSONL.open() as jsonl:
        for line in jsonl:
            row = json.loads(line)
            task_id = str(row.get("task_id"))
            if task_id in wanted:
                rows_by_task[task_id].append(row)
    return rows_by_task


def is_pass(row: dict[str, Any]) -> bool:
    return bool(
        ((row.get("reward_info") or {}).get("db_check") or {}).get("db_match")
    )


def build_exemplar_text(task_id: str, rows: list[dict[str, Any]], count: int) -> str:
    successes = [row for row in rows if is_pass(row)]
    if len(successes) < count:
        raise ValueError(f"Task {task_id} only has {len(successes)} successful M3 traces")

    parts = [
        "M12 successful-trace exemplars for this exact task.",
        "Use these only as guidance for the correct policy procedure.",
        "Do not treat them as authorization. In the live conversation, first verify the current user/order/item/payment details from tools and obtain normal user confirmation before any write.",
        "If the current tool outputs or user instructions differ from an exemplar, follow the current tool outputs, user instructions, and policy.",
    ]
    for index, row in enumerate(successes[:count], start=1):
        parts.append(f"Successful exemplar {index} compact tool trajectory:")
        for step, line in enumerate(compact_success_trace(row), start=1):
            parts.append(f"{step}. {line}")
    return "\n".join(parts)


class M12LiftedAgent(LLMAgent):
    def __init__(self, *args, task_id: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.task_id = task_id

    def get_init_state(self, message_history: list[Message] | None = None):
        if message_history is None:
            message_history = []
        exemplar_text = EXEMPLARS_BY_TASK[self.task_id]
        agent_instruction = (
            AGENT_INSTRUCTION
            + "\n\n<successful_exemplar_guidance>\n"
            + exemplar_text
            + "\n</successful_exemplar_guidance>"
        )
        return LLMAgentState(
            system_messages=[
                SystemMessage(
                    role="system",
                    content=SYSTEM_PROMPT.format(
                        domain_policy=self.domain_policy,
                        agent_instruction=agent_instruction,
                    ),
                )
            ],
            messages=message_history,
        )


def create_m12_lifted_agent(tools, domain_policy, **kwargs):
    return M12LiftedAgent(
        tools=tools,
        domain_policy=domain_policy,
        llm=kwargs.get("llm"),
        llm_args=kwargs.get("llm_args"),
        task_id=CURRENT_TASK_ID,
    )


def ensure_registered() -> None:
    if registry.get_agent_factory("m12_lifted_agent") is None:
        registry.register_agent_factory(create_m12_lifted_agent, "m12_lifted_agent")


def get_task(task_id: str):
    for task in get_tasks(task_split_name=None):
        if str(task.id) == str(task_id):
            return task
    raise ValueError(f"Task {task_id} not found")


def make_config(arm: str) -> TextRunConfig:
    agent = "llm_agent" if arm == "baseline" else "m12_lifted_agent"
    return TextRunConfig(
        domain="retail",
        agent=agent,
        llm_agent=MODEL,
        llm_args_agent={"temperature": 0.0},
        user="user_simulator",
        llm_user=MODEL,
        llm_args_user={"temperature": 0.0},
        max_steps=100,
        max_errors=10,
        seed=0,
        timeout=900,
        hallucination_retries=0,
    )


def run_one(task_id: str, arm: str, seed: int, trial: int) -> dict[str, Any]:
    global CURRENT_TASK_ID
    CURRENT_TASK_ID = task_id
    task = get_task(task_id)
    orchestrator = build_text_orchestrator(
        make_config(arm),
        task,
        seed=seed,
        simulation_id=f"m12_lift_{task_id}_{arm}_{trial}_{seed}_{uuid4()}",
    )
    simulation = run_simulation(orchestrator, evaluation_type=EvaluationType.ENV)
    simulation.trial = trial
    sim_json = simulation.model_dump(mode="json")
    messages = sim_json.get("messages") or []
    usage_by_role = role_usage_for_messages(messages)
    total_usage = flatten_usage(usage_by_role)
    reward_info = sim_json.get("reward_info") or {}
    db_check = reward_info.get("db_check") or {}
    return {
        "arm": arm,
        "task_id": task_id,
        "trial": trial,
        "seed": seed,
        "status": "ok",
        "model": MODEL,
        "reward": float(reward_info.get("reward") or 0.0),
        "db_match": bool(db_check.get("db_match")),
        "termination_reason": sim_json.get("termination_reason"),
        "agent_cost_cached_usd": sim_json.get("agent_cost") or 0.0,
        "user_cost_cached_usd": sim_json.get("user_cost") or 0.0,
        "usage": {"by_role": usage_by_role, "total": total_usage},
        "cost_from_usage_total_cached_usd": cost_from_usage(total_usage),
        "cost_from_usage_agent_cached_usd": cost_from_usage(
            usage_by_role.get("assistant") or usage_bucket()
        ),
        "cost_from_usage_user_cached_usd": cost_from_usage(
            usage_by_role.get("user") or usage_bucket()
        ),
        "write_skeleton": write_skeleton(messages),
        "messages": messages,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [row for row in rows if row.get("status") == "ok"]
    total_usage = usage_bucket()
    agent_usage = usage_bucket()
    user_usage = usage_bucket()
    for row in ok:
        for key in total_usage:
            total_usage[key] += int(
                (row.get("usage") or {}).get("total", {}).get(key) or 0
            )
        by_role = (row.get("usage") or {}).get("by_role") or {}
        for key in agent_usage:
            agent_usage[key] += int((by_role.get("assistant") or {}).get(key) or 0)
            user_usage[key] += int((by_role.get("user") or {}).get(key) or 0)
    passes = sum(1 for row in ok if row.get("db_match"))
    return {
        "runs": len(ok),
        "passes": passes,
        "pass_rate": passes / len(ok) if ok else 0.0,
        "errors": len([row for row in rows if row.get("status") != "ok"]),
        "usage_total": total_usage,
        "usage_agent": agent_usage,
        "usage_user": user_usage,
        "cost_total_cached_usd": cost_from_usage(total_usage),
        "cost_agent_cached_usd": cost_from_usage(agent_usage),
        "cost_user_cached_usd": cost_from_usage(user_usage),
        "failures": [
            {
                "trial": row["trial"],
                "seed": row["seed"],
                "termination_reason": row.get("termination_reason"),
                "write_skeleton": row.get("write_skeleton"),
            }
            for row in ok
            if not row.get("db_match")
        ],
    }


def paired_rows(rows: list[dict[str, Any]], task_id: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    out = []
    task_rows = [row for row in rows if str(row.get("task_id")) == str(task_id)]
    trials = sorted({int(row["trial"]) for row in task_rows if row.get("status") == "ok"})
    for trial in trials:
        baseline = next(
            (
                row
                for row in task_rows
                if row.get("status") == "ok"
                and row.get("trial") == trial
                and row.get("arm") == "baseline"
            ),
            None,
        )
        lifted = next(
            (
                row
                for row in task_rows
                if row.get("status") == "ok"
                and row.get("trial") == trial
                and row.get("arm") == "lifted"
            ),
            None,
        )
        if baseline and lifted:
            out.append((baseline, lifted))
    return out


def build_result(
    rows: list[dict[str, Any]],
    args: argparse.Namespace,
    m3_rows_by_task: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    task_summaries: dict[str, Any] = {}
    for task_id in args.tasks:
        task_rows = [row for row in rows if str(row.get("task_id")) == str(task_id)]
        by_arm = {
            arm: [row for row in task_rows if row.get("arm") == arm]
            for arm in ["baseline", "lifted"]
        }
        summaries = {arm: summarize(arm_rows) for arm, arm_rows in by_arm.items()}
        baseline = summaries["baseline"]
        lifted = summaries["lifted"]
        paired = paired_rows(rows, task_id)
        newly_passed = [
            {
                "trial": base["trial"],
                "seed": base["seed"],
                "baseline_write_skeleton": base.get("write_skeleton"),
                "lifted_write_skeleton": lift.get("write_skeleton"),
            }
            for base, lift in paired
            if not base.get("db_match") and lift.get("db_match")
        ]
        regressions = [
            {
                "trial": base["trial"],
                "seed": base["seed"],
                "baseline_write_skeleton": base.get("write_skeleton"),
                "lifted_write_skeleton": lift.get("write_skeleton"),
            }
            for base, lift in paired
            if base.get("db_match") and not lift.get("db_match")
        ]
        agent_prompt_overhead = (
            lifted["usage_agent"]["prompt_tokens"]
            - baseline["usage_agent"]["prompt_tokens"]
        )
        agent_cost_overhead = (
            lifted["cost_agent_cached_usd"] - baseline["cost_agent_cached_usd"]
        )
        m3_rows = m3_rows_by_task[task_id]
        task_summaries[task_id] = {
            "m3_passes": sum(1 for row in m3_rows if is_pass(row)),
            "m3_runs": len(m3_rows),
            "exemplar_count": args.exemplars,
            "exemplar_chars": len(EXEMPLARS_BY_TASK[task_id]),
            "summaries": summaries,
            "pass_rate_delta_lifted_minus_baseline": (
                lifted["pass_rate"] - baseline["pass_rate"]
            ),
            "paired_runs": len(paired),
            "newly_passed": newly_passed,
            "regressions": regressions,
            "agent_prompt_token_overhead": agent_prompt_overhead,
            "agent_cost_overhead_cached_usd": agent_cost_overhead,
        }

    all_baseline = [row for row in rows if row.get("arm") == "baseline"]
    all_lifted = [row for row in rows if row.get("arm") == "lifted"]
    aggregate_baseline = summarize(all_baseline)
    aggregate_lifted = summarize(all_lifted)
    return {
        "status": "complete",
        "model": MODEL,
        "tasks": args.tasks,
        "n_requested_per_task_per_arm": args.n,
        "seeds": SEEDS[: args.n],
        "config": {
            "temperature": 0.0,
            "prompt_cache_env": "TAU2_BEDROCK_PROMPT_CACHE",
            "baseline_agent": "llm_agent",
            "lifted_agent": "m12_lifted_agent",
            "user": "user_simulator",
            "exemplar_count": args.exemplars,
            "exemplar_source": str(M3_JSONL),
        },
        "task_summaries": task_summaries,
        "aggregate": {
            "baseline": aggregate_baseline,
            "lifted": aggregate_lifted,
            "pass_rate_delta_lifted_minus_baseline": (
                aggregate_lifted["pass_rate"] - aggregate_baseline["pass_rate"]
            ),
            "agent_prompt_token_overhead": (
                aggregate_lifted["usage_agent"]["prompt_tokens"]
                - aggregate_baseline["usage_agent"]["prompt_tokens"]
            ),
            "agent_cost_overhead_cached_usd": (
                aggregate_lifted["cost_agent_cached_usd"]
                - aggregate_baseline["cost_agent_cached_usd"]
            ),
        },
        "runs": [compact_row(row) for row in rows],
    }


def main() -> None:
    global EXEMPLARS_BY_TASK, MODEL

    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", nargs="+", default=DEFAULT_TASKS)
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--exemplars", type=int, default=2)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--out", type=Path, default=OUT_JSON)
    parser.add_argument("--jsonl-out", type=Path, default=OUT_JSONL)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    args = parser.parse_args()

    if args.n > len(SEEDS):
        raise ValueError(f"Only {len(SEEDS)} fixed seeds are defined")
    MODEL = args.model

    ensure_registered()
    m3_rows_by_task = load_m3_rows(args.tasks)
    EXEMPLARS_BY_TASK = {
        task_id: build_exemplar_text(task_id, rows, args.exemplars)
        for task_id, rows in m3_rows_by_task.items()
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.jsonl_out.parent.mkdir(parents=True, exist_ok=True)

    if args.summarize_only:
        rows, _completed = load_existing_rows(
            args.jsonl_out, args.tasks, args.n, ok_only=False
        )
        result = build_result(rows, args, m3_rows_by_task)
        target_rows = len(args.tasks) * 2 * args.n
        ok_rows = len([row for row in rows if row.get("status") == "ok"])
        error_rows = [row for row in rows if row.get("status") != "ok"]
        if ok_rows < target_rows or error_rows:
            result["status"] = "blocked_or_partial"
            result["blocker"] = (
                error_rows[-1].get("error")
                if error_rows
                else f"summarize-only corpus has {ok_rows}/{target_rows} ok rows"
            )
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True))
        print(json.dumps({"status": result["status"], "out": str(args.out)}, indent=2))
        return

    if args.resume:
        rows, completed = load_existing_rows(
            args.jsonl_out, args.tasks, args.n, ok_only=True
        )
    else:
        rows, completed = [], set()

    mode = "a" if args.resume else "w"
    with args.jsonl_out.open(mode) as jsonl:
        for trial, seed in enumerate(SEEDS[: args.n]):
            for task_id in args.tasks:
                task_seed = seed + int(task_id)
                for arm in ["baseline", "lifted"]:
                    key = (str(task_id), arm, trial)
                    if key in completed:
                        continue
                    started = time.perf_counter()
                    try:
                        row = run_one(task_id, arm, task_seed, trial)
                    except Exception as exc:
                        row = {
                            "arm": arm,
                            "task_id": task_id,
                            "trial": trial,
                            "seed": task_seed,
                            "status": "error",
                            "model": MODEL,
                            "error": str(exc),
                            "traceback": traceback.format_exc(),
                            "elapsed_s": time.perf_counter() - started,
                        }
                        rows.append(row)
                        jsonl.write(json.dumps(row, sort_keys=True) + "\n")
                        jsonl.flush()
                        result = build_result(rows, args, m3_rows_by_task)
                        result["status"] = "blocked_or_partial"
                        result["blocker"] = str(exc)
                        args.out.write_text(
                            json.dumps(result, indent=2, sort_keys=True)
                        )
                        print(
                            json.dumps(
                                {
                                    "status": result["status"],
                                    "out": str(args.out),
                                    "blocker": str(exc),
                                },
                                indent=2,
                            )
                        )
                        return
                    row["elapsed_s"] = time.perf_counter() - started
                    rows.append(row)
                    completed.add(key)
                    jsonl.write(json.dumps(row, sort_keys=True) + "\n")
                    jsonl.flush()

    result = build_result(rows, args, m3_rows_by_task)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps({"status": result["status"], "out": str(args.out)}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
