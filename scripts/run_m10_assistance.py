#!/usr/bin/env python3
"""Run the M10 assistance-tier probe.

The assisted agent stays an ordinary LLM agent for all decisions and writes.
This harness only:
- derives suggestive procedure context from prior traces,
- pre-executes read-only lookups observed in successful traces, and
- injects a compact read-only packet into the agent prompt.

No deterministic write script or promotion gate is used here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from statistics import mean
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
from tau2.data_model.message import SystemMessage  # noqa: E402
from tau2.data_model.simulation import TextRunConfig  # noqa: E402
from tau2.domains.retail.environment import get_tasks  # noqa: E402
from tau2.environment.environment import Environment  # noqa: E402
from tau2.evaluator.evaluator import EvaluationType  # noqa: E402
from tau2.registry import registry  # noqa: E402
from tau2.runner.build import build_text_orchestrator  # noqa: E402
from tau2.runner.simulation import run_simulation  # noqa: E402


SOSOG_ROOT = Path(__file__).resolve().parents[1]
MODEL = "bedrock/us.anthropic.claude-sonnet-4-6"
TARGET_FAMILY = "compound_pending_order_modification"
TARGET_TASK_IDS = ["41", "71", "78", "97"]
DERIVATION_TASK_IDS = ["78", "97"]
HELD_OUT_TASK_IDS = ["41", "71"]
BIAS_TEST_TASK_ID = "71"
SEEDS = [626729, 373753, 361454]

M2_TRACE = SOSOG_ROOT / "traces" / "m2" / "retail_db_checkable_baseline.jsonl"
M3_TRACE = (
    SOSOG_ROOT
    / "traces"
    / "m3"
    / "retail_db_checkable_n10_partial_valid_before_daily_quota.jsonl"
)
OUT_JSON = SOSOG_ROOT / "metrics" / "m10_assistance_results.json"
OUT_JSONL = SOSOG_ROOT / "traces" / "m10" / "compound_modify_assisted.jsonl"

READ_TOOLS = {
    "find_user_id_by_email",
    "find_user_id_by_name_zip",
    "get_item_details",
    "get_order_details",
    "get_product_details",
    "get_user_details",
    "list_all_product_types",
}
WRITE_TOOLS = {
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
}

TRACE_ROWS: list[dict[str, Any]] = []
PREFETCH_CALLS_BY_TASK: dict[str, list[dict[str, Any]]] = {}
PLAN_SCAFFOLD = ""


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


def cost_from_usage(bucket: dict[str, int], *, cached: bool = True) -> float:
    input_rate = 3.00
    output_rate = 15.00
    cache_write_rate = 3.75
    cache_read_rate = 0.30
    if cached:
        input_cost = (
            bucket["noncached_input_tokens"] * input_rate
            + bucket["cache_creation_input_tokens"] * cache_write_rate
            + bucket["cache_read_input_tokens"] * cache_read_rate
        )
    else:
        input_cost = bucket["prompt_tokens"] * input_rate
    return (input_cost + bucket["completion_tokens"] * output_rate) / 1_000_000


def aggregate_usage(rows: list[dict[str, Any]], role: str | None = None) -> dict[str, int]:
    total = usage_bucket()
    for row in rows:
        usage = row.get("usage") or {}
        if role is None:
            source = usage.get("total") or row.get("total_usage") or {}
            for key in total:
                total[key] += int(source.get(key) or 0)
            continue
        source = (usage.get("by_role") or {}).get(role) or {}
        for key in total:
            total[key] += int(source.get(key) or 0)
    return total


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


def flatten_role_usage(role_usage: dict[str, dict[str, int]]) -> dict[str, int]:
    total = usage_bucket()
    for bucket in role_usage.values():
        for key in total:
            total[key] += int(bucket.get(key) or 0)
    return total


def call_signature(name: str, arguments: dict[str, Any] | None) -> str:
    return f"{name}({json.dumps(arguments or {}, sort_keys=True, separators=(',', ':'))})"


def decode_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def load_trace_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in [M2_TRACE, M3_TRACE]:
        with path.open() as handle:
            for line in handle:
                row = json.loads(line)
                task_id = str(row["task"]["id"])
                if task_id not in TARGET_TASK_IDS:
                    continue
                row["source_trace"] = str(path.relative_to(SOSOG_ROOT))
                rows.append(row)
    return rows


def action_sequence(row: dict[str, Any]) -> list[dict[str, Any]]:
    return row.get("action_sequence") or []


def is_pass(row: dict[str, Any]) -> bool:
    reward_info = row.get("reward_info") or {}
    db_check = reward_info.get("db_check") or {}
    return float(reward_info.get("reward") or 0.0) >= 1.0 and bool(
        db_check.get("db_match")
    )


def write_skeleton_from_actions(actions: list[dict[str, Any]]) -> list[str]:
    return [
        call_signature(action["name"], action.get("arguments"))
        for action in actions
        if action.get("name") in WRITE_TOOLS
    ]


def read_call_from_action(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": action["name"],
        "arguments": action.get("arguments") or {},
        "signature": call_signature(action["name"], action.get("arguments")),
    }


def derive_prefetch_calls(task_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    passing = [row for row in rows if str(row["task"]["id"]) == task_id and is_pass(row)]
    if not passing:
        return []

    signatures_by_row: list[set[str]] = []
    calls_by_sig: dict[str, dict[str, Any]] = {}
    first_order: list[str] = []
    for row in passing:
        seen: set[str] = set()
        for action in action_sequence(row):
            name = action.get("name")
            if name not in READ_TOOLS:
                continue
            call = read_call_from_action(action)
            sig = call["signature"]
            calls_by_sig[sig] = call
            if sig not in first_order:
                first_order.append(sig)
            seen.add(sig)
        signatures_by_row.append(seen)

    stable_sigs = set.intersection(*signatures_by_row) if signatures_by_row else set()
    return [calls_by_sig[sig] for sig in first_order if sig in stable_sigs]


def derive_plan_scaffold(rows: list[dict[str, Any]]) -> str:
    derivation_rows = [
        row
        for row in rows
        if str(row["task"]["id"]) in DERIVATION_TASK_IDS and is_pass(row)
    ]
    read_skeleton_counts: Counter[str] = Counter()
    write_family_counts: Counter[str] = Counter()
    for row in derivation_rows:
        read_names = [
            action["name"]
            for action in action_sequence(row)
            if action.get("name") in READ_TOOLS
        ]
        read_skeleton_counts[" -> ".join(read_names)] += 1
        for action in action_sequence(row):
            name = action.get("name")
            if name in WRITE_TOOLS:
                write_family_counts[name] += 1

    top_read = read_skeleton_counts.most_common(1)[0][0] if read_skeleton_counts else ""
    write_names = ", ".join(name for name, _ in write_family_counts.most_common())
    return f"""
This is trace-derived assistance for tasks that combine pending-order address
changes, item changes, and sometimes cancellation/default-address updates.

Typical read shape observed in successful derivation traces:
{top_read}

Write tools seen in the family evidence:
{write_names}

Suggested procedure, not a rule:
1. Identify the customer and inspect the relevant orders.
2. Inspect product variants only when an item change or exchange is actually requested.
3. Explain the proposed changes and ask for explicit yes/no confirmation before any write.
4. Make only the writes supported by the current conversation and retail policy.
5. Deviate from this scaffold whenever the user changes their mind, asks for an
   extra action, omits confirmation, or the read-only context contradicts the usual path.

The scaffold is advisory. You remain responsible for every decision and every
write-tool argument. You may call any read tool again if this packet is
insufficient or suspicious. Never execute a write just because it appears in
the usual procedure.
""".strip()


def compact_address(address: dict[str, Any] | None) -> dict[str, Any] | None:
    if not address:
        return None
    return {
        "address1": address.get("address1"),
        "address2": address.get("address2"),
        "city": address.get("city"),
        "state": address.get("state"),
        "country": address.get("country"),
        "zip": address.get("zip"),
    }


def summarize_order(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_id": order.get("order_id"),
        "user_id": order.get("user_id"),
        "status": order.get("status"),
        "address": compact_address(order.get("address")),
        "items": [
            {
                "name": item.get("name"),
                "product_id": item.get("product_id"),
                "item_id": item.get("item_id"),
                "options": item.get("options"),
                "price": item.get("price"),
            }
            for item in order.get("items", [])
        ],
        "payment_history": order.get("payment_history"),
    }


def summarize_user(user: dict[str, Any]) -> dict[str, Any]:
    methods = []
    for method_id, method in sorted((user.get("payment_methods") or {}).items()):
        methods.append(
            {
                "id": method_id,
                "source": method.get("source"),
                "balance": method.get("balance"),
            }
        )
    return {
        "user_id": user.get("user_id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "address": compact_address(user.get("address")),
        "payment_methods": methods,
        "orders": user.get("orders"),
    }


def summarize_product(product: dict[str, Any]) -> dict[str, Any]:
    variants = []
    for item_id, variant in sorted((product.get("variants") or {}).items()):
        if not variant.get("available"):
            continue
        variants.append(
            {
                "item_id": item_id,
                "options": variant.get("options"),
                "price": variant.get("price"),
                "available": variant.get("available"),
            }
        )
    return {
        "product_id": product.get("product_id"),
        "name": product.get("name"),
        "available_variants": variants,
    }


def summarize_read_result(name: str, result: Any) -> Any:
    decoded = decode_jsonish(result)
    if name.startswith("find_user_id"):
        return decoded
    if name == "get_user_details" and isinstance(decoded, dict):
        return summarize_user(decoded)
    if name == "get_order_details" and isinstance(decoded, dict):
        return summarize_order(decoded)
    if name == "get_product_details" and isinstance(decoded, dict):
        return summarize_product(decoded)
    return decoded


def execute_prefetch_packet(task_id: str, tools: list[Any]) -> dict[str, Any]:
    tools_by_name = {tool.name: tool for tool in tools}
    calls = PREFETCH_CALLS_BY_TASK.get(task_id, [])
    packet_calls = []
    for index, call in enumerate(calls, start=1):
        name = call["name"]
        arguments = call["arguments"]
        if name not in READ_TOOLS:
            raise ValueError(f"M10 prefetch attempted non-read tool: {name}")
        if name in WRITE_TOOLS:
            raise ValueError(f"M10 prefetch attempted write tool: {name}")
        if name not in tools_by_name:
            raise ValueError(f"M10 prefetch unknown tool: {name}")
        response = tools_by_name[name](**arguments)
        response_json = Environment.to_json_str(response)
        packet_calls.append(
            {
                "index": index,
                "tool": name,
                "arguments": arguments,
                "summary": summarize_read_result(name, response_json),
            }
        )

    return {
        "task_id": task_id,
        "target_family": TARGET_FAMILY,
        "prefetch_policy": "read-only stable calls from prior passing traces",
        "prefetch_calls": packet_calls,
        "prefetch_write_calls": [
            call for call in calls if call.get("name") in WRITE_TOOLS
        ],
        "plan_scaffold": PLAN_SCAFFOLD,
    }


class M10AssistedLLMAgent(LLMAgent):
    def __init__(
        self,
        tools: list[Any],
        domain_policy: str,
        task: Any,
        llm: str,
        llm_args: dict[str, Any] | None = None,
    ):
        super().__init__(
            tools=tools,
            domain_policy=domain_policy,
            llm=llm,
            llm_args=llm_args,
        )
        self.task = task

    def get_init_state(self, message_history=None):
        if message_history is None:
            message_history = []
        packet = execute_prefetch_packet(str(self.task.id), self.tools)
        packet_text = json.dumps(packet, indent=2, sort_keys=True)
        agent_instruction = (
            AGENT_INSTRUCTION
            + "\n\nYou may use the <sosog_assistance> packet below. It is "
            "read-only, advisory assistance. It does not authorize a write. "
            "You still decide what to do from the current conversation and policy."
        )
        system_prompt = (
            SYSTEM_PROMPT.format(
                domain_policy=self.domain_policy,
                agent_instruction=agent_instruction,
            )
            + "\n\n<sosog_assistance>\n"
            + packet_text
            + "\n</sosog_assistance>"
        )
        return LLMAgentState(
            system_messages=[SystemMessage(role="system", content=system_prompt)],
            messages=message_history,
        )


def create_m10_assisted_agent(tools, domain_policy, **kwargs):
    return M10AssistedLLMAgent(
        tools=tools,
        domain_policy=domain_policy,
        task=kwargs.get("task"),
        llm=kwargs.get("llm"),
        llm_args=kwargs.get("llm_args"),
    )


def ensure_registered() -> None:
    if registry.get_agent_factory("m10_assisted_agent") is None:
        registry.register_agent_factory(create_m10_assisted_agent, "m10_assisted_agent")


def task_by_id(task_id: str):
    for task in get_tasks(task_split_name=None):
        if str(task.id) == str(task_id):
            return task
    raise ValueError(f"Task {task_id} not found")


def run_one(task_id: str, seed: int, trial: int) -> dict[str, Any]:
    task = task_by_id(task_id)
    config = TextRunConfig(
        domain="retail",
        agent="m10_assisted_agent",
        llm_agent=MODEL,
        llm_args_agent={"temperature": 0.0},
        user="user_simulator",
        llm_user=MODEL,
        llm_args_user={"temperature": 0.0},
        max_steps=200,
        max_errors=10,
        seed=seed,
        timeout=900,
        hallucination_retries=0,
    )
    orchestrator = build_text_orchestrator(
        config,
        task,
        seed=seed,
        simulation_id=f"m10_assisted_{task_id}_{trial}_{uuid4()}",
    )
    simulation = run_simulation(orchestrator, evaluation_type=EvaluationType.ENV)
    simulation.trial = trial
    sim_json = simulation.model_dump(mode="json")
    messages = sim_json.get("messages") or []
    usage_by_role = role_usage_for_messages(messages)
    total_usage = flatten_role_usage(usage_by_role)
    reward_info = sim_json.get("reward_info") or {}
    db_check = reward_info.get("db_check") or {}
    actions = extract_action_sequence(messages)
    return {
        "task_id": task_id,
        "trial": trial,
        "seed": seed,
        "status": "ok",
        "simulation": sim_json,
        "reward": float(reward_info.get("reward") or 0.0),
        "db_match": bool(db_check.get("db_match")),
        "agent_cost_cached_usd": sim_json.get("agent_cost") or 0.0,
        "user_cost_cached_usd": sim_json.get("user_cost") or 0.0,
        "total_cost_cached_usd": (sim_json.get("agent_cost") or 0.0)
        + (sim_json.get("user_cost") or 0.0),
        "usage": {"by_role": usage_by_role, "total": total_usage},
        "write_skeleton": write_skeleton_from_actions(actions),
        "all_tool_calls": [
            {
                "name": action["name"],
                "arguments": action["arguments"],
            }
            for action in actions
        ],
        "prefetch_calls": PREFETCH_CALLS_BY_TASK.get(task_id, []),
        "prefetch_write_call_count": sum(
            1 for call in PREFETCH_CALLS_BY_TASK.get(task_id, []) if call["name"] in WRITE_TOOLS
        ),
    }


def extract_action_sequence(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sequence: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for message in messages:
        for tool_call in message.get("tool_calls") or []:
            item = {
                "turn_idx": message.get("turn_idx"),
                "call_id": tool_call.get("id"),
                "name": tool_call.get("name"),
                "arguments": tool_call.get("arguments") or {},
                "result": None,
            }
            sequence.append(item)
            pending.append(item)
        if message.get("role") == "tool":
            target = pending.pop(0) if pending else None
            if target is not None:
                target["result"] = message.get("content")
    return sequence


def raw_rows_for_comparison(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        task_id = str(row["task"]["id"])
        if task_id not in TARGET_TASK_IDS:
            continue
        seed = row.get("simulation", {}).get("seed")
        trial = row.get("simulation", {}).get("trial")
        if seed not in SEEDS:
            continue
        if row.get("source_trace") != str(M3_TRACE.relative_to(SOSOG_ROOT)):
            continue
        actions = action_sequence(row)
        selected.append(
            {
                "task_id": task_id,
                "trial": trial,
                "seed": seed,
                "status": "ok",
                "reward": float((row.get("reward_info") or {}).get("reward") or 0.0),
                "db_match": bool(
                    ((row.get("reward_info") or {}).get("db_check") or {}).get(
                        "db_match"
                    )
                ),
                "agent_cost_cached_usd": (row.get("costs") or {}).get(
                    "agent_cached_usd"
                )
                or 0.0,
                "user_cost_cached_usd": (row.get("costs") or {}).get(
                    "user_cached_usd"
                )
                or 0.0,
                "total_cost_cached_usd": (row.get("costs") or {}).get(
                    "total_cached_usd"
                )
                or 0.0,
                "usage": row.get("usage") or {},
                "write_skeleton": write_skeleton_from_actions(actions),
                "all_tool_calls": [
                    {"name": action["name"], "arguments": action.get("arguments") or {}}
                    for action in actions
                ],
            }
        )
    return sorted(selected, key=lambda item: (int(item["task_id"]), item["trial"]))


def summarize_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row.get("status") == "ok"]
    pass_count = sum(1 for row in valid if row.get("db_match"))
    total_cost = sum(float(row.get("total_cost_cached_usd") or 0.0) for row in valid)
    agent_cost = sum(float(row.get("agent_cost_cached_usd") or 0.0) for row in valid)
    user_cost = sum(float(row.get("user_cost_cached_usd") or 0.0) for row in valid)
    total_usage = aggregate_usage(valid)
    agent_usage = aggregate_usage(valid, "assistant")
    user_usage = aggregate_usage(valid, "user")
    by_task = {}
    for task_id in TARGET_TASK_IDS:
        task_rows = [row for row in valid if row["task_id"] == task_id]
        by_task[task_id] = {
            "runs": len(task_rows),
            "passes": sum(1 for row in task_rows if row.get("db_match")),
            "pass_rate": (
                sum(1 for row in task_rows if row.get("db_match")) / len(task_rows)
                if task_rows
                else None
            ),
            "avg_total_cost_cached_usd": (
                mean(float(row.get("total_cost_cached_usd") or 0.0) for row in task_rows)
                if task_rows
                else None
            ),
            "avg_agent_cost_cached_usd": (
                mean(float(row.get("agent_cost_cached_usd") or 0.0) for row in task_rows)
                if task_rows
                else None
            ),
            "distinct_write_skeletons": sorted(
                {" -> ".join(row.get("write_skeleton") or []) or "none" for row in task_rows}
            ),
        }
    return {
        "runs": len(valid),
        "pass_count": pass_count,
        "fail_count": len(valid) - pass_count,
        "pass_rate": pass_count / len(valid) if valid else None,
        "total_cost_cached_usd": total_cost,
        "agent_cost_cached_usd": agent_cost,
        "user_cost_cached_usd": user_cost,
        "avg_total_cost_cached_usd": total_cost / len(valid) if valid else None,
        "avg_agent_cost_cached_usd": agent_cost / len(valid) if valid else None,
        "usage_total": total_usage,
        "usage_agent": agent_usage,
        "usage_user": user_usage,
        "recomputed_total_cost_cached_usd": cost_from_usage(total_usage),
        "recomputed_agent_cost_cached_usd": cost_from_usage(agent_usage),
        "recomputed_user_cost_cached_usd": cost_from_usage(user_usage),
        "by_task": by_task,
    }


def pct_reduction(raw_value: float | int | None, assisted_value: float | int | None) -> float | None:
    if raw_value in (None, 0) or assisted_value is None:
        return None
    return (float(raw_value) - float(assisted_value)) / float(raw_value)


def compare(raw: dict[str, Any], assisted: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_cost_reduction_pct": pct_reduction(
            raw.get("total_cost_cached_usd"), assisted.get("total_cost_cached_usd")
        ),
        "agent_cost_reduction_pct": pct_reduction(
            raw.get("agent_cost_cached_usd"), assisted.get("agent_cost_cached_usd")
        ),
        "total_token_reduction_pct": pct_reduction(
            raw["usage_total"].get("total_tokens"), assisted["usage_total"].get("total_tokens")
        ),
        "agent_token_reduction_pct": pct_reduction(
            raw["usage_agent"].get("total_tokens"), assisted["usage_agent"].get("total_tokens")
        ),
        "agent_call_reduction_pct": pct_reduction(
            raw["usage_agent"].get("calls"), assisted["usage_agent"].get("calls")
        ),
        "raw_pass_rate": raw.get("pass_rate"),
        "assisted_pass_rate": assisted.get("pass_rate"),
        "accuracy_delta_pp": (
            (assisted.get("pass_rate") - raw.get("pass_rate")) * 100
            if assisted.get("pass_rate") is not None and raw.get("pass_rate") is not None
            else None
        ),
    }


def per_case_table(raw_rows: list[dict[str, Any]], assisted_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_by_key = {(row["task_id"], row["trial"], row["seed"]): row for row in raw_rows}
    rows = []
    for assisted in sorted(assisted_rows, key=lambda item: (int(item["task_id"]), item["trial"])):
        key = (assisted["task_id"], assisted["trial"], assisted["seed"])
        raw = raw_by_key.get(key)
        rows.append(
            {
                "task_id": assisted["task_id"],
                "trial": assisted["trial"],
                "seed": assisted["seed"],
                "raw_pass": raw.get("db_match") if raw else None,
                "assisted_pass": assisted.get("db_match"),
                "raw_total_cost_cached_usd": raw.get("total_cost_cached_usd") if raw else None,
                "assisted_total_cost_cached_usd": assisted.get("total_cost_cached_usd"),
                "raw_agent_calls": ((raw.get("usage") or {}).get("by_role") or {}).get(
                    "assistant", {}
                ).get("calls")
                if raw
                else None,
                "assisted_agent_calls": (
                    (assisted.get("usage") or {}).get("by_role") or {}
                ).get("assistant", {}).get("calls"),
                "raw_writes": raw.get("write_skeleton") if raw else None,
                "assisted_writes": assisted.get("write_skeleton"),
            }
        )
    return rows


def task_family_note() -> dict[str, Any]:
    return {
        "family": TARGET_FAMILY,
        "task_ids": TARGET_TASK_IDS,
        "derivation_task_ids": DERIVATION_TASK_IDS,
        "held_out_task_ids": HELD_OUT_TASK_IDS,
        "bias_test_task_id": BIAS_TEST_TASK_ID,
        "why_unpromoted": (
            "M3 partial marked tasks 41, 71, 78, and 97 as flaky-looking or "
            "unpromoted: 41/71 had DB failures, while 78/97 passed but had "
            "multiple passing write skeletons. There is no single stable "
            "family write skeleton safe enough for promotion."
        ),
        "bias_test": (
            "Task 71 is the explicit scaffold-bias test: the user's initial "
            "request includes address plus multiple item changes, but the user "
            "changes payment choice and decides to modify only the backpack. "
            "The assisted agent must deviate from any frozen item-change plan."
        ),
    }


def build_assistance() -> None:
    global TRACE_ROWS, PREFETCH_CALLS_BY_TASK, PLAN_SCAFFOLD
    TRACE_ROWS = load_trace_rows()
    PLAN_SCAFFOLD = derive_plan_scaffold(TRACE_ROWS)
    PREFETCH_CALLS_BY_TASK = {
        task_id: derive_prefetch_calls(task_id, TRACE_ROWS)
        for task_id in TARGET_TASK_IDS
    }


def is_quota_error(exc: BaseException) -> bool:
    text = "".join(traceback.format_exception_only(type(exc), exc))
    return "Too many tokens per day" in text or "RateLimitError" in text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT_JSON)
    parser.add_argument("--jsonl-out", type=Path, default=OUT_JSONL)
    parser.add_argument("--task-ids", nargs="*", default=TARGET_TASK_IDS)
    parser.add_argument("--seeds", nargs="*", type=int, default=SEEDS)
    args = parser.parse_args()

    if not os.environ.get("TAU2_BEDROCK_PROMPT_CACHE"):
        print("warning: TAU2_BEDROCK_PROMPT_CACHE is not set", file=sys.stderr)

    build_assistance()
    ensure_registered()
    raw_rows = raw_rows_for_comparison(TRACE_ROWS)
    assisted_rows: list[dict[str, Any]] = []
    infrastructure_errors: list[dict[str, Any]] = []

    args.jsonl_out.parent.mkdir(parents=True, exist_ok=True)
    with args.jsonl_out.open("w") as jsonl:
        for trial, seed in enumerate(args.seeds):
            for task_id in args.task_ids:
                try:
                    row = run_one(str(task_id), seed, trial)
                    assisted_rows.append(row)
                    jsonl.write(
                        json.dumps(
                            {
                                "task_id": row["task_id"],
                                "trial": row["trial"],
                                "seed": row["seed"],
                                "reward": row["reward"],
                                "db_match": row["db_match"],
                                "costs": {
                                    "agent_cached_usd": row["agent_cost_cached_usd"],
                                    "user_cached_usd": row["user_cost_cached_usd"],
                                    "total_cached_usd": row["total_cost_cached_usd"],
                                },
                                "usage": row["usage"],
                                "write_skeleton": row["write_skeleton"],
                                "all_tool_calls": row["all_tool_calls"],
                                "simulation": row["simulation"],
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    print(
                        f"ok task={task_id} trial={trial} seed={seed} "
                        f"db={row['db_match']} cost={row['total_cost_cached_usd']:.6f}"
                    )
                except Exception as exc:  # noqa: BLE001
                    error = {
                        "task_id": str(task_id),
                        "trial": trial,
                        "seed": seed,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                    infrastructure_errors.append(error)
                    print(
                        f"error task={task_id} trial={trial} seed={seed} "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                    if is_quota_error(exc):
                        print("quota-blocked; stopping M10 run", file=sys.stderr)
                        break
            if infrastructure_errors and is_quota_error(Exception(infrastructure_errors[-1]["error"])):
                break

    raw_summary = summarize_runs(raw_rows)
    assisted_summary = summarize_runs(assisted_rows)
    comparison = compare(raw_summary, assisted_summary)
    cases = per_case_table(raw_rows, assisted_rows)
    safety = {
        "prefetch_write_call_count": sum(
            row.get("prefetch_write_call_count", 0) for row in assisted_rows
        ),
        "all_prefetch_calls_read_only": all(
            call["name"] in READ_TOOLS
            for calls in PREFETCH_CALLS_BY_TASK.values()
            for call in calls
        ),
        "agent_made_every_trajectory_write": True,
        "deterministic_write_scripts_used": False,
        "promotion_gate_used": False,
    }
    bias_task_rows = [
        row for row in assisted_rows if row["task_id"] == BIAS_TEST_TASK_ID
    ]
    bias_result = {
        "task_id": BIAS_TEST_TASK_ID,
        "assisted_passes": sum(1 for row in bias_task_rows if row.get("db_match")),
        "assisted_runs": len(bias_task_rows),
        "raw_same_seed_passes": raw_summary["by_task"][BIAS_TEST_TASK_ID]["passes"],
        "raw_same_seed_runs": raw_summary["by_task"][BIAS_TEST_TASK_ID]["runs"],
        "deviated_correctly": (
            len(bias_task_rows) > 0
            and all(row.get("db_match") for row in bias_task_rows)
        ),
        "assisted_write_skeletons": [
            " -> ".join(row.get("write_skeleton") or []) or "none"
            for row in bias_task_rows
        ],
    }
    output = {
        "milestone": "M10",
        "status": "complete" if not infrastructure_errors else "partial_or_blocked",
        "model": MODEL,
        "prompt_cache_enabled": bool(os.environ.get("TAU2_BEDROCK_PROMPT_CACHE")),
        "target": task_family_note(),
        "seeds": args.seeds,
        "raw_baseline_source": str(M3_TRACE.relative_to(SOSOG_ROOT)),
        "raw_summary_same_seed_m3_partial": raw_summary,
        "assisted_summary": assisted_summary,
        "comparison": comparison,
        "prefetch_calls_by_task": PREFETCH_CALLS_BY_TASK,
        "plan_scaffold": PLAN_SCAFFOLD,
        "per_case": cases,
        "bias_test_result": bias_result,
        "safety_sanity": safety,
        "infrastructure_errors": infrastructure_errors,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": output["status"], "comparison": comparison}, indent=2))
    return 0 if not infrastructure_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
