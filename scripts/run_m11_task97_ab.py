#!/usr/bin/env python3
"""M11 task-97 controlled A/B.

Runs stock full-agent task 97 against a decomposed variant that scripts only
the deterministic read prefix, then delegates the volatile tail to the normal
Sonnet agent.  The arms are interleaved by seed so quota blocks leave a clear
N reached in each arm.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger
from pydantic import Field

logger.remove()

from tau2.agent.llm_agent import (  # noqa: E402
    AGENT_INSTRUCTION,
    SYSTEM_PROMPT,
    LLMAgent,
    LLMAgentState,
)
from tau2.data_model.message import (  # noqa: E402
    AssistantMessage,
    Message,
    MultiToolMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.data_model.simulation import TextRunConfig  # noqa: E402
from tau2.domains.retail.environment import get_tasks  # noqa: E402
from tau2.evaluator.evaluator import EvaluationType  # noqa: E402
from tau2.registry import registry  # noqa: E402
from tau2.runner.build import build_text_orchestrator  # noqa: E402
from tau2.runner.simulation import run_simulation  # noqa: E402


SOSOG_ROOT = Path(__file__).resolve().parents[1]
MODEL = "bedrock/us.anthropic.claude-sonnet-4-6"
TASK_ID = "97"
OUT_JSON = SOSOG_ROOT / "metrics" / "m11_task97_ab_results.json"
OUT_JSONL = SOSOG_ROOT / "traces" / "m11" / "task97_ab.jsonl"

SEEDS = [
    970001,
    970019,
    970037,
    970061,
    970079,
    970091,
    970123,
    970153,
    970181,
    970213,
    970241,
    970267,
    970303,
    970337,
    970361,
    970397,
    970421,
    970451,
    970477,
    970511,
]

TASK97_PREFIX_CALLS = [
    {
        "name": "find_user_id_by_name_zip",
        "arguments": {"first_name": "Yusuf", "last_name": "Li", "zip": "91148"},
    },
    {"name": "get_user_details", "arguments": {"user_id": "yusuf_li_7255"}},
    {"name": "get_order_details", "arguments": {"order_id": "#W6750959"}},
    {"name": "get_order_details", "arguments": {"order_id": "#W3407479"}},
    {"name": "get_product_details", "arguments": {"product_id": "4768869376"}},
]

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


def decode_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def shape_check(name: str, result: Any) -> None:
    decoded = decode_jsonish(result)
    if name.startswith("find_user_id"):
        if not isinstance(decoded, str) or not decoded:
            raise ValueError(f"{name} result is not a non-empty user id string")
        return
    if name == "get_user_details":
        required = {"user_id", "orders", "payment_methods", "address"}
    elif name == "get_order_details":
        required = {"order_id", "user_id", "status", "items", "payment_history"}
    elif name == "get_product_details":
        required = {"name", "product_id", "variants"}
    else:
        required = set()
    if required:
        if not isinstance(decoded, dict):
            raise ValueError(f"{name} result is not an object")
        missing = sorted(required - set(decoded))
        if missing:
            raise ValueError(f"{name} result missing required fields: {missing}")


def call_signature(name: str, arguments: dict[str, Any] | None) -> str:
    return f"{name}({json.dumps(arguments or {}, sort_keys=True, separators=(',', ':'))})"


def write_skeleton(messages: list[dict[str, Any]]) -> list[str]:
    out = []
    for message in messages:
        for tool_call in message.get("tool_calls") or []:
            if tool_call.get("name") in WRITE_TOOLS:
                out.append(
                    call_signature(tool_call["name"], tool_call.get("arguments") or {})
                )
    return out


class M11Task97State(LLMAgentState):
    prefix_index: int = 0
    auth_prompted: bool = False
    handed_to_llm: bool = False
    prefix_results: list[dict[str, Any]] = Field(default_factory=list)


class M11Task97DecomposedAgent(LLMAgent):
    def get_init_state(self, message_history: list[Message] | None = None):
        if message_history is None:
            message_history = []
        agent_instruction = (
            AGENT_INSTRUCTION
            + "\n\nYou are continuing after an M11 deterministic read-only "
            "prefix. The prior tool results are validated lookup results only; "
            "they do not authorize any write. Continue naturally, follow the "
            "retail policy, obtain any needed confirmation from the user, and "
            "perform the remaining decision/write tail if appropriate. Repeat "
            "prefix reads only if the handoff state is missing or suspicious."
        )
        return M11Task97State(
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

    def _append_input(self, message: Message, state: M11Task97State) -> None:
        if isinstance(message, MultiToolMessage):
            state.messages.extend(message.tool_messages)
            for tool_message in message.tool_messages:
                self._record_prefix_result(tool_message, state)
            return
        state.messages.append(message)
        if isinstance(message, ToolMessage):
            self._record_prefix_result(message, state)

    def _record_prefix_result(
        self, message: ToolMessage, state: M11Task97State
    ) -> None:
        if len(state.prefix_results) >= len(TASK97_PREFIX_CALLS):
            return
        expected = TASK97_PREFIX_CALLS[len(state.prefix_results)]
        shape_check(expected["name"], message.content)
        if message.error:
            raise ValueError(f"Prefix tool errored: {expected['name']}")
        state.prefix_results.append(
            {
                "name": expected["name"],
                "arguments": expected["arguments"],
                "content": message.content,
                "error": message.error,
            }
        )

    def _prefix_tool_message(self, state: M11Task97State) -> AssistantMessage:
        call = TASK97_PREFIX_CALLS[state.prefix_index]
        if call["name"] not in READ_TOOLS:
            raise ValueError(f"Unsafe scripted prefix call: {call['name']}")
        state.prefix_index += 1
        return AssistantMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id=f"m11ab_{TASK_ID}_{state.prefix_index}_{uuid4().hex[:8]}",
                    name=call["name"],
                    arguments=call["arguments"],
                    requestor="assistant",
                )
            ],
            cost=0.0,
            usage=None,
        )

    def generate_next_message(
        self, message: Message, state: M11Task97State
    ) -> tuple[AssistantMessage, M11Task97State]:
        if state.handed_to_llm:
            return super().generate_next_message(message, state)

        if not state.auth_prompted:
            self._append_input(message, state)
            assistant_message = AssistantMessage(
                role="assistant",
                content=(
                    "I can help with both. First I need to verify your identity. "
                    "Could you provide your email address, or your name and ZIP code?"
                ),
                cost=0.0,
                usage=None,
            )
            state.auth_prompted = True
            state.messages.append(assistant_message)
            return assistant_message, state

        if state.prefix_index < len(TASK97_PREFIX_CALLS):
            self._append_input(message, state)
            assistant_message = self._prefix_tool_message(state)
            state.messages.append(assistant_message)
            return assistant_message, state

        if isinstance(message, MultiToolMessage):
            for tool_message in message.tool_messages:
                self._record_prefix_result(tool_message, state)
        elif isinstance(message, ToolMessage):
            self._record_prefix_result(message, state)
        state.handed_to_llm = True
        return super().generate_next_message(message, state)


def create_m11_task97_decomposed_agent(tools, domain_policy, **kwargs):
    return M11Task97DecomposedAgent(
        tools=tools,
        domain_policy=domain_policy,
        llm=kwargs.get("llm"),
        llm_args=kwargs.get("llm_args"),
    )


def ensure_registered() -> None:
    if registry.get_agent_factory("m11_task97_decomposed_agent") is None:
        registry.register_agent_factory(
            create_m11_task97_decomposed_agent, "m11_task97_decomposed_agent"
        )


def task_97():
    for task in get_tasks(task_split_name=None):
        if str(task.id) == TASK_ID:
            return task
    raise ValueError("Task 97 not found")


def make_config(arm: str) -> TextRunConfig:
    agent = "llm_agent" if arm == "baseline" else "m11_task97_decomposed_agent"
    return TextRunConfig(
        domain="retail",
        agent=agent,
        llm_agent=MODEL,
        llm_args_agent={"temperature": 0.0},
        user="user_simulator",
        llm_user=MODEL,
        llm_args_user={"temperature": 0.0},
        max_steps=80,
        max_errors=10,
        seed=0,
        timeout=900,
        hallucination_retries=0,
    )


def run_one(arm: str, seed: int, trial: int) -> dict[str, Any]:
    config = make_config(arm)
    task = task_97()
    orchestrator = build_text_orchestrator(
        config,
        task,
        seed=seed,
        simulation_id=f"m11_task97_ab_{arm}_{trial}_{seed}_{uuid4()}",
    )
    simulation = run_simulation(orchestrator, evaluation_type=EvaluationType.ENV)
    simulation.trial = trial
    sim_json = simulation.model_dump(mode="json")
    messages = sim_json.get("messages") or []
    usage_by_role = role_usage_for_messages(messages)
    total_usage = flatten_usage(usage_by_role)
    reward_info = sim_json.get("reward_info") or {}
    db_check = reward_info.get("db_check") or {}
    prefix_model_calls = 0
    prefix_results = []
    if arm == "decomposed":
        agent_state = getattr(orchestrator, "agent_state", None)
        prefix_results = list(getattr(agent_state, "prefix_results", []) or [])
        prefix_model_calls = sum(
            1
            for message in messages
            if message.get("role") == "assistant"
            and message.get("usage")
            and any(
                (tool_call.get("name") in READ_TOOLS)
                for tool_call in (message.get("tool_calls") or [])
            )
        )
    return {
        "arm": arm,
        "task_id": TASK_ID,
        "trial": trial,
        "seed": seed,
        "status": "ok",
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
        "prefix_model_calls": prefix_model_calls,
        "prefix_results_count": len(prefix_results),
        "messages": messages,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [row for row in rows if row.get("status") == "ok"]
    total_usage = usage_bucket()
    agent_usage = usage_bucket()
    user_usage = usage_bucket()
    for row in ok:
        for key in total_usage:
            total_usage[key] += int((row.get("usage") or {}).get("total", {}).get(key) or 0)
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


def build_result(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    by_arm = {
        arm: [row for row in rows if row.get("arm") == arm]
        for arm in ["baseline", "decomposed"]
    }
    summaries = {arm: summarize(arm_rows) for arm, arm_rows in by_arm.items()}
    baseline = summaries["baseline"]
    decomposed = summaries["decomposed"]
    pass_rate_delta = decomposed["pass_rate"] - baseline["pass_rate"]
    if baseline["runs"] == 0 or decomposed["runs"] == 0:
        conclusion = "quota_or_runtime_blocked"
    elif abs(pass_rate_delta) <= 0.05:
        conclusion = "within_noise"
    elif decomposed["pass_rate"] < baseline["pass_rate"]:
        conclusion = "decomposition_caused_or_amplified_regression"
    else:
        conclusion = "decomposition_not_harmful_in_this_sample"
    return {
        "status": "complete",
        "task_id": TASK_ID,
        "model": MODEL,
        "n_requested_per_arm": args.n,
        "seeds": SEEDS[: args.n],
        "config": {
            "temperature": 0.0,
            "prompt_cache_env": "TAU2_BEDROCK_PROMPT_CACHE",
            "baseline_agent": "llm_agent",
            "decomposed_agent": "m11_task97_decomposed_agent",
            "user": "user_simulator",
        },
        "summaries": summaries,
        "pass_rate_delta_decomposed_minus_baseline": pass_rate_delta,
        "conclusion_rule": conclusion,
        "runs": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--out", type=Path, default=OUT_JSON)
    parser.add_argument("--jsonl-out", type=Path, default=OUT_JSONL)
    args = parser.parse_args()

    if args.n > len(SEEDS):
        raise ValueError(f"Only {len(SEEDS)} fixed seeds are defined")

    ensure_registered()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.jsonl_out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    with args.jsonl_out.open("w") as jsonl:
        for trial, seed in enumerate(SEEDS[: args.n]):
            for arm in ["baseline", "decomposed"]:
                try:
                    row = run_one(arm, seed, trial)
                except Exception as exc:
                    row = {
                        "arm": arm,
                        "task_id": TASK_ID,
                        "trial": trial,
                        "seed": seed,
                        "status": "error",
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                    rows.append(row)
                    jsonl.write(json.dumps(row, sort_keys=True) + "\n")
                    jsonl.flush()
                    result = build_result(rows, args)
                    result["status"] = "blocked_or_partial"
                    result["blocker"] = str(exc)
                    args.out.write_text(json.dumps(result, indent=2, sort_keys=True))
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
                rows.append(row)
                jsonl.write(json.dumps(row, sort_keys=True) + "\n")
                jsonl.flush()

    result = build_result(rows, args)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps({"status": result["status"], "out": str(args.out)}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
