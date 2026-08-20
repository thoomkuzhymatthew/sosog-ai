#!/usr/bin/env python3
"""M11 task-decomposition proof harness.

This is intentionally narrow: it analyzes the six M3 decompose candidates,
then runs matched handoff probes for selected tasks.  The handoff starts at
the first non-crystallized tail step from the saved M3 trace; all earlier
messages are included as zero-cost initial history, so measured model spend is
for the tail only.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter, defaultdict
from copy import deepcopy
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
from tau2.data_model.message import (  # noqa: E402
    AssistantMessage,
    Message,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.data_model.simulation import TextRunConfig  # noqa: E402
from tau2.data_model.tasks import InitialState, Task  # noqa: E402
from tau2.domains.retail.environment import get_environment, get_tasks  # noqa: E402
from tau2.environment.environment import Environment  # noqa: E402
from tau2.evaluator.evaluator import EvaluationType  # noqa: E402
from tau2.registry import registry  # noqa: E402
from tau2.runner.build import build_text_orchestrator  # noqa: E402
from tau2.runner.simulation import run_simulation  # noqa: E402
from tau2.user.user_simulator import UserSimulator  # noqa: E402
from tau2.user.user_simulator_base import (  # noqa: E402
    HalfDuplexUser,
    UserState,
    ValidUserInputMessage,
)


SOSOG_ROOT = Path(__file__).resolve().parents[1]
MODEL = "bedrock/us.anthropic.claude-sonnet-4-6"
FINAL_TRACE = (
    SOSOG_ROOT / "traces" / "m3" / "retail_db_checkable_n10_final_valid.jsonl"
)
OUT_JSON = SOSOG_ROOT / "metrics" / "m11_decomposition_results.json"
OUT_JSONL = SOSOG_ROOT / "traces" / "m11" / "decomposition_probe.jsonl"

DECOMPOSE_CANDIDATES = ["30", "78", "87", "97", "100", "112"]
DEFAULT_PROBE_TASKS = ["78", "97"]
CURRENT_TAIL_USER_REPLAY: list[str] = []

WRITE_TOOLS = {
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
}

READ_TOOLS = {
    "calculate",
    "find_user_id_by_email",
    "find_user_id_by_name_zip",
    "get_item_details",
    "get_order_details",
    "get_product_details",
    "get_user_details",
    "list_all_product_types",
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


def canonical(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return canonical(json.loads(value))
        except json.JSONDecodeError:
            return value
    if isinstance(value, dict):
        return {key: canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


def canonical_hash(value: Any) -> str:
    import hashlib

    blob = json.dumps(canonical(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def call_signature(name: str, arguments: dict[str, Any] | None) -> str:
    return f"{name}({json.dumps(arguments or {}, sort_keys=True, separators=(',', ':'))})"


def message_tool_calls(row: dict[str, Any]) -> list[dict[str, Any]]:
    calls = []
    for msg_idx, message in enumerate(row.get("messages") or []):
        for call_idx, tool_call in enumerate(message.get("tool_calls") or []):
            calls.append(
                {
                    "message_index": msg_idx,
                    "call_index": call_idx,
                    "name": tool_call["name"],
                    "arguments": tool_call.get("arguments") or {},
                    "signature": call_signature(
                        tool_call["name"], tool_call.get("arguments") or {}
                    ),
                    "requestor": tool_call.get("requestor") or "assistant",
                    "id": tool_call.get("id"),
                }
            )
    return calls


def tool_results_by_call(row: dict[str, Any]) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    paired = []
    for msg_idx, message in enumerate(row.get("messages") or []):
        for tool_call in message.get("tool_calls") or []:
            pending.append(tool_call)
        if message.get("role") == "tool":
            call = pending.pop(0) if pending else None
            if call is None:
                continue
            paired.append(
                {
                    "name": call.get("name"),
                    "arguments": call.get("arguments") or {},
                    "signature": call_signature(
                        call.get("name"), call.get("arguments") or {}
                    ),
                    "content": message.get("content"),
                    "error": bool(message.get("error")),
                    "message_index": msg_idx,
                }
            )
    return paired


def load_m3_rows() -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with FINAL_TRACE.open() as handle:
        for line in handle:
            row = json.loads(line)
            task_id = str(row["task_id"])
            if task_id in DECOMPOSE_CANDIDATES:
                rows[task_id].append(row)
    for task_rows in rows.values():
        task_rows.sort(key=lambda row: int(row["trial"]))
    return rows


def lcp_signatures(sequences: list[list[str]]) -> list[str]:
    prefix = []
    for items in zip(*sequences):
        if len(set(items)) != 1:
            break
        prefix.append(items[0])
    return prefix


def derive_alignment(rows_by_task: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    alignments = {}
    for task_id in DECOMPOSE_CANDIDATES:
        rows = rows_by_task[task_id]
        sequences = [[call["signature"] for call in message_tool_calls(row)] for row in rows]
        lcp = lcp_signatures(sequences)

        first_row_calls = message_tool_calls(rows[0])
        lcp_calls = first_row_calls[: len(lcp)]
        safe_prefix_calls = []
        blocked_by_common_write = None
        for call in lcp_calls:
            if call["name"] in WRITE_TOOLS or call["name"] not in READ_TOOLS:
                blocked_by_common_write = call
                break
            safe_prefix_calls.append(
                {
                    "name": call["name"],
                    "arguments": call["arguments"],
                    "signature": call["signature"],
                }
            )

        divergence_options: Counter[str] = Counter()
        divergence_trials: dict[str, list[int]] = defaultdict(list)
        for row, sequence in zip(rows, sequences):
            next_sig = (
                sequence[len(safe_prefix_calls)]
                if len(sequence) > len(safe_prefix_calls)
                else "<END>"
            )
            divergence_options[next_sig] += 1
            divergence_trials[next_sig].append(int(row["trial"]))

        alignments[task_id] = {
            "task_id": task_id,
            "run_count": len(rows),
            "longest_common_prefix_length": len(lcp),
            "safe_read_prefix_length": len(safe_prefix_calls),
            "safe_prefix_calls": safe_prefix_calls,
            "blocked_by_common_write": blocked_by_common_write,
            "divergence_options": [
                {
                    "signature": signature,
                    "count": count,
                    "trials": divergence_trials[signature],
                }
                for signature, count in divergence_options.most_common()
            ],
            "strict_all_runs": len(rows) == 10 and len(safe_prefix_calls) > 0,
            "read_only": blocked_by_common_write is None
            or len(safe_prefix_calls) < len(lcp_calls),
        }
    return alignments


def shape_check(name: str, result: Any) -> None:
    decoded = canonical(result)
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
    elif name == "get_item_details":
        required = {"item_id", "options", "available", "price"}
    else:
        required = set()
    if required:
        if not isinstance(decoded, dict):
            raise ValueError(f"{name} result is not an object")
        missing = sorted(required - set(decoded))
        if missing:
            raise ValueError(f"{name} result missing required fields: {missing}")


def validate_prefix_packet(packet: dict[str, Any]) -> None:
    if packet.get("prefix_model_calls") != 0:
        raise ValueError("Prefix packet claims non-zero model calls")
    calls = packet.get("calls") or []
    if not calls:
        raise ValueError("Prefix packet has no calls")
    for call in calls:
        name = call.get("name")
        if name not in READ_TOOLS or name in WRITE_TOOLS:
            raise ValueError(f"Unsafe prefix call: {name}")
        if call.get("mutates_state"):
            raise ValueError(f"Prefix call mutates state: {name}")
        if call.get("error"):
            raise ValueError(f"Prefix call errored: {name}")
        shape_check(name, call.get("result"))


def execute_prefix(task_id: str, prefix_calls: list[dict[str, Any]]) -> dict[str, Any]:
    environment = get_environment()
    tools_by_name = {tool.name: tool for tool in environment.get_tools()}
    packet_calls = []
    for index, call in enumerate(prefix_calls, start=1):
        name = call["name"]
        arguments = call["arguments"]
        if name not in READ_TOOLS or name in WRITE_TOOLS:
            raise ValueError(f"M11 refused unsafe prefix call: {name}")
        if name not in tools_by_name:
            raise ValueError(f"M11 prefix call uses unknown tool: {name}")
        if environment._is_mutating_tool(name):
            raise ValueError(f"M11 refused mutating prefix call: {name}")
        try:
            result = tools_by_name[name](**arguments)
            result_json = Environment.to_json_str(result)
            packet_calls.append(
                {
                    "index": index,
                    "name": name,
                    "arguments": arguments,
                    "result": result_json,
                    "result_hash": canonical_hash(result_json),
                    "mutates_state": False,
                    "error": False,
                }
            )
        except Exception as exc:  # pragma: no cover - surfaced in result JSON
            packet_calls.append(
                {
                    "index": index,
                    "name": name,
                    "arguments": arguments,
                    "result": str(exc),
                    "result_hash": canonical_hash(str(exc)),
                    "mutates_state": False,
                    "error": True,
                }
            )
            raise
    packet = {
        "task_id": task_id,
        "prefix_model_calls": 0,
        "calls": packet_calls,
    }
    validate_prefix_packet(packet)
    return packet


def validate_prefix_against_traces(
    task_id: str,
    rows: list[dict[str, Any]],
    prefix_calls: list[dict[str, Any]],
    packet: dict[str, Any],
) -> dict[str, Any]:
    expected_hashes = [call["result_hash"] for call in packet["calls"]]
    mismatches = []
    per_trial_hashes = []
    for row in rows:
        paired = tool_results_by_call(row)
        trace_prefix = paired[: len(prefix_calls)]
        trial_hashes = [canonical_hash(item["content"]) for item in trace_prefix]
        per_trial_hashes.append(
            {
                "trial": int(row["trial"]),
                "hashes": trial_hashes,
            }
        )
        if trial_hashes != expected_hashes:
            mismatches.append(
                {
                    "trial": int(row["trial"]),
                    "expected": expected_hashes,
                    "actual": trial_hashes,
                }
            )
    if mismatches:
        raise ValueError(f"Task {task_id} prefix output mismatch: {mismatches[:2]}")

    second_packet = execute_prefix(task_id, prefix_calls)
    deterministic_twice = [
        call["result_hash"] for call in second_packet["calls"]
    ] == expected_hashes

    corrupted = deepcopy(packet)
    for call in corrupted["calls"]:
        name = call["name"]
        decoded = canonical(call["result"])
        if name.startswith("find_user_id"):
            call["result"] = ""
            break
        if not isinstance(decoded, dict):
            continue
        if name == "get_user_details":
            decoded.pop("user_id", None)
            call["result"] = decoded
            break
        if name == "get_order_details":
            decoded.pop("order_id", None)
            call["result"] = decoded
            break
        if name == "get_product_details":
            decoded.pop("product_id", None)
            call["result"] = decoded
            break
        if name == "get_item_details":
            decoded.pop("item_id", None)
            call["result"] = decoded
            break
    else:
        corrupted["calls"][0]["mutates_state"] = True

    gate_caught_corruption = False
    try:
        validate_prefix_packet(corrupted)
    except ValueError:
        gate_caught_corruption = True

    return {
        "trace_hashes_match_prefix": not mismatches,
        "deterministic_two_fresh_executions": deterministic_twice,
        "per_trial_hashes": per_trial_hashes,
        "gate_caught_corruption": gate_caught_corruption,
    }


def message_from_json(raw: dict[str, Any]) -> Message:
    role = raw.get("role")
    common = {
        "turn_idx": None,
        "timestamp": raw.get("timestamp"),
    }
    tool_calls = None
    if raw.get("tool_calls") is not None:
        tool_calls = [ToolCall.model_validate(call) for call in raw.get("tool_calls") or []]
    if role == "assistant":
        return AssistantMessage(
            role="assistant",
            content=raw.get("content") or None,
            tool_calls=tool_calls,
            **common,
        )
    if role == "user":
        return UserMessage(
            role="user",
            content=raw.get("content") or None,
            tool_calls=tool_calls,
            **common,
        )
    if role == "tool":
        return ToolMessage(
            id=raw["id"],
            role="tool",
            content=raw.get("content"),
            requestor=raw.get("requestor") or "assistant",
            error=bool(raw.get("error")),
            **common,
        )
    raise ValueError(f"Unsupported message role in handoff history: {role}")


def build_handoff_history(
    row: dict[str, Any], safe_prefix_len: int
) -> tuple[list[Message], dict[str, Any]]:
    calls = message_tool_calls(row)
    if len(calls) <= safe_prefix_len:
        raise ValueError("No tail call after safe prefix")
    divergence_call = calls[safe_prefix_len]
    divergence_message_index = divergence_call["message_index"]
    if divergence_call["call_index"] == 0:
        raw_history = row["messages"][:divergence_message_index]
        handoff_end_message_index = divergence_message_index - 1
    else:
        raw_history = row["messages"][:divergence_message_index]
        prefix_assistant = deepcopy(row["messages"][divergence_message_index])
        prefix_tool_calls = prefix_assistant.get("tool_calls", [])[
            : divergence_call["call_index"]
        ]
        prefix_ids = {tool_call["id"] for tool_call in prefix_tool_calls}
        prefix_assistant["tool_calls"] = prefix_tool_calls
        raw_history.append(prefix_assistant)

        found_prefix_tool_results = 0
        handoff_end_message_index = divergence_message_index
        for message_index, message in enumerate(
            row["messages"][divergence_message_index + 1 :],
            start=divergence_message_index + 1,
        ):
            if message.get("role") != "tool":
                break
            if message.get("id") not in prefix_ids:
                continue
            raw_history.append(deepcopy(message))
            handoff_end_message_index = message_index
            found_prefix_tool_results += 1
            if found_prefix_tool_results == len(prefix_tool_calls):
                break
        if found_prefix_tool_results != len(prefix_tool_calls):
            raise ValueError("Could not split bundled prefix tool results cleanly")
    history = [message_from_json(message) for message in raw_history]
    if not history or not isinstance(history[-1], (UserMessage, ToolMessage)):
        raise ValueError("Handoff history must end with a user or prefix tool message")
    tail_user_messages = [
        message.get("content") or ""
        for index, message in enumerate(row["messages"])
        if index > handoff_end_message_index and message.get("role") == "user"
    ]
    return history, {
        "divergence_signature": divergence_call["signature"],
        "divergence_message_index": divergence_message_index,
        "divergence_call_index": divergence_call["call_index"],
        "last_user_message": history[-1].content,
        "history_message_count": len(history),
        "handoff_last_role": history[-1].role,
        "tail_user_replay_messages": len(tail_user_messages),
        "handoff_end_message_index": handoff_end_message_index,
        "_tail_user_replay": tail_user_messages,
    }


class M11PrefixTailAgent(LLMAgent):
    def __init__(
        self,
        tools: list[Any],
        domain_policy: str,
        task: Task,
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
        agent_instruction = (
            AGENT_INSTRUCTION
            + "\n\nYou are resuming after an M11 deterministic prefix. The "
            "conversation history already contains the validated read-only "
            "lookup results from that prefix. Treat those prior tool results "
            "as trusted context, but do not execute any write unless the "
            "conversation supports it and the user has confirmed. You may "
            "repeat a read only if the handoff state is missing or suspicious. "
            "The deterministic prefix did not authorize any write."
        )
        system_prompt = SYSTEM_PROMPT.format(
            domain_policy=self.domain_policy,
            agent_instruction=agent_instruction,
        )
        return LLMAgentState(
            system_messages=[SystemMessage(role="system", content=system_prompt)],
            messages=message_history,
        )


class M11ReplayUser(HalfDuplexUser[UserState]):
    def __init__(
        self,
        instructions: str | None = None,
        tools: list[Any] | None = None,
        llm: str | None = None,
        llm_args: dict[str, Any] | None = None,
        persona_config: Any | None = None,
    ):
        super().__init__(instructions=instructions, tools=tools)
        self.response_count = 0
        self.replay_messages = list(CURRENT_TAIL_USER_REPLAY)

    def get_init_state(self, message_history=None) -> UserState:
        if message_history is None:
            message_history = []
        return UserState(system_messages=[], messages=message_history)

    def generate_next_message(
        self, message: ValidUserInputMessage, state: UserState
    ) -> tuple[UserMessage, UserState]:
        self.response_count += 1
        if self.replay_messages:
            text = self.replay_messages.pop(0)
        else:
            text = "No, that's everything. Thanks. ###STOP###"
            if self.response_count == 1 and isinstance(message, AssistantMessage):
                content = (message.content or "").lower()
                if "confirm" in content or "proceed" in content or "yes/no" in content:
                    text = "Yes, please go ahead."
        user_message = UserMessage(role="user", content=text, cost=0.0, usage=None)
        state.messages.append(user_message)
        return user_message, state

    @classmethod
    def is_stop(cls, message: UserMessage) -> bool:
        return UserSimulator.is_stop(message)


def create_m11_prefix_tail_agent(tools, domain_policy, **kwargs):
    return M11PrefixTailAgent(
        tools=tools,
        domain_policy=domain_policy,
        task=kwargs.get("task"),
        llm=kwargs.get("llm"),
        llm_args=kwargs.get("llm_args"),
    )


def ensure_registered() -> None:
    if registry.get_agent_factory("m11_prefix_tail_agent") is None:
        registry.register_agent_factory(
            create_m11_prefix_tail_agent, "m11_prefix_tail_agent"
        )
    try:
        registry.get_user_constructor("m11_replay_user")
    except KeyError:
        registry.register_user(M11ReplayUser, "m11_replay_user")


def task_by_id(task_id: str) -> Task:
    for task in get_tasks(task_split_name=None):
        if str(task.id) == str(task_id):
            return task
    raise ValueError(f"Task {task_id} not found")


def with_initial_history(task: Task, history: list[Message]) -> Task:
    return task.model_copy(
        update={
            "initial_state": InitialState(
                initialization_data=None,
                initialization_actions=None,
                message_history=history,
            )
        }
    )


def write_skeleton(messages: list[dict[str, Any]]) -> list[str]:
    out = []
    for message in messages:
        for tool_call in message.get("tool_calls") or []:
            if tool_call.get("name") in WRITE_TOOLS:
                out.append(
                    call_signature(tool_call["name"], tool_call.get("arguments") or {})
                )
    return out


def run_one(
    row: dict[str, Any],
    alignment: dict[str, Any],
) -> dict[str, Any]:
    global CURRENT_TAIL_USER_REPLAY
    task_id = str(row["task_id"])
    history, handoff = build_handoff_history(
        row, int(alignment["safe_read_prefix_length"])
    )
    CURRENT_TAIL_USER_REPLAY = handoff.pop("_tail_user_replay")
    task = with_initial_history(task_by_id(task_id), history)
    config = TextRunConfig(
        domain="retail",
        agent="m11_prefix_tail_agent",
        llm_agent=MODEL,
        llm_args_agent={"temperature": 0.0},
        user="m11_replay_user",
        llm_user=MODEL,
        llm_args_user={},
        max_steps=80,
        max_errors=10,
        seed=int(row["seed"]),
        timeout=900,
        hallucination_retries=0,
    )
    orchestrator = build_text_orchestrator(
        config,
        task,
        seed=int(row["seed"]),
        simulation_id=f"m11_{task_id}_{row['trial']}_{uuid4()}",
    )
    simulation = run_simulation(orchestrator, evaluation_type=EvaluationType.ENV)
    simulation.trial = int(row["trial"])
    sim_json = simulation.model_dump(mode="json")
    messages = sim_json.get("messages") or []
    usage_by_role = role_usage_for_messages(messages)
    total_usage = flatten_usage(usage_by_role)
    reward_info = sim_json.get("reward_info") or {}
    db_check = reward_info.get("db_check") or {}
    return {
        "task_id": task_id,
        "trial": int(row["trial"]),
        "seed": int(row["seed"]),
        "status": "ok",
        "handoff": handoff,
        "reward": float(reward_info.get("reward") or 0.0),
        "db_match": bool(db_check.get("db_match")),
        "agent_cost_cached_usd": sim_json.get("agent_cost") or 0.0,
        "user_cost_cached_usd": sim_json.get("user_cost") or 0.0,
        "total_cost_cached_usd": (sim_json.get("agent_cost") or 0.0)
        + (sim_json.get("user_cost") or 0.0),
        "usage": {"by_role": usage_by_role, "total": total_usage},
        "write_skeleton": write_skeleton(messages),
        "termination_reason": sim_json.get("termination_reason"),
        "messages": messages,
    }


def baseline_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        messages = row.get("messages") or []
        usage_by_role = role_usage_for_messages(messages)
        total_usage = flatten_usage(usage_by_role)
        reward_info = row.get("reward_info") or {}
        db_check = reward_info.get("db_check") or {}
        out.append(
            {
                "task_id": str(row["task_id"]),
                "trial": int(row["trial"]),
                "seed": int(row["seed"]),
                "reward": float(reward_info.get("reward") or 0.0),
                "db_match": bool(db_check.get("db_match")),
                "agent_cost_cached_usd": row.get("agent_cost") or 0.0,
                "user_cost_cached_usd": row.get("user_cost") or 0.0,
                "total_cost_cached_usd": (row.get("agent_cost") or 0.0)
                + (row.get("user_cost") or 0.0),
                "usage": {"by_role": usage_by_role, "total": total_usage},
                "write_skeleton": write_skeleton(messages),
            }
        )
    return out


def summarize_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row.get("status", "ok") == "ok"]
    total_usage = usage_bucket()
    agent_usage = usage_bucket()
    for row in valid:
        usage = (row.get("usage") or {}).get("total") or {}
        for key in total_usage:
            total_usage[key] += int(usage.get(key) or 0)
        role_usage = (row.get("usage") or {}).get("by_role") or {}
        assistant_usage = role_usage.get("assistant") or {}
        for key in agent_usage:
            agent_usage[key] += int(assistant_usage.get(key) or 0)
    return {
        "runs": len(valid),
        "db_passes": sum(1 for row in valid if row.get("db_match")),
        "pass_rate": (sum(1 for row in valid if row.get("db_match")) / len(valid))
        if valid
        else 0.0,
        "total_cost_cached_usd": sum(
            float(row.get("total_cost_cached_usd") or 0.0) for row in valid
        ),
        "agent_cost_cached_usd": sum(
            float(row.get("agent_cost_cached_usd") or 0.0) for row in valid
        ),
        "user_cost_cached_usd": sum(
            float(row.get("user_cost_cached_usd") or 0.0) for row in valid
        ),
        "usage_total": total_usage,
        "usage_agent": agent_usage,
        "cost_from_usage_total_cached_usd": cost_from_usage(total_usage, cached=True),
        "cost_from_usage_agent_cached_usd": cost_from_usage(agent_usage, cached=True),
    }


def compare_task(
    task_id: str,
    baseline: list[dict[str, Any]],
    m11: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_summary = summarize_runs(baseline)
    m11_summary = summarize_runs(m11)
    return {
        "task_id": task_id,
        "baseline": baseline_summary,
        "m11": m11_summary,
        "pass_rate_preserved": m11_summary["db_passes"]
        >= baseline_summary["db_passes"],
        "agent_cost_saved_cached_usd": baseline_summary[
            "cost_from_usage_agent_cached_usd"
        ]
        - m11_summary["cost_from_usage_agent_cached_usd"],
        "total_cost_saved_cached_usd": baseline_summary[
            "cost_from_usage_total_cached_usd"
        ]
        - m11_summary["cost_from_usage_total_cached_usd"],
        "agent_token_saved": baseline_summary["usage_agent"]["total_tokens"]
        - m11_summary["usage_agent"]["total_tokens"],
        "total_token_saved": baseline_summary["usage_total"]["total_tokens"]
        - m11_summary["usage_total"]["total_tokens"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", nargs="+", default=DEFAULT_PROBE_TASKS)
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument("--offline-only", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT_JSON)
    parser.add_argument("--jsonl-out", type=Path, default=OUT_JSONL)
    args = parser.parse_args()

    ensure_registered()
    rows_by_task = load_m3_rows()
    alignments = derive_alignment(rows_by_task)

    prefix_validation = {}
    for task_id, alignment in alignments.items():
        prefix_calls = alignment["safe_prefix_calls"]
        if not prefix_calls:
            prefix_validation[task_id] = {
                "status": "no_safe_prefix",
                "reason": "No read-only common prefix calls.",
            }
            continue
        try:
            packet = execute_prefix(task_id, prefix_calls)
            validation = validate_prefix_against_traces(
                task_id, rows_by_task[task_id], prefix_calls, packet
            )
            prefix_validation[task_id] = {
                "status": "ok",
                "packet": packet,
                "validation": validation,
            }
        except Exception as exc:
            prefix_validation[task_id] = {
                "status": "failed",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }

    result: dict[str, Any] = {
        "status": "offline_validated" if args.offline_only else "started",
        "model": MODEL,
        "trace_source": str(FINAL_TRACE.relative_to(SOSOG_ROOT)),
        "candidate_tasks": DECOMPOSE_CANDIDATES,
        "probe_tasks": [str(task) for task in args.tasks],
        "trial_limit": args.trials,
        "alignment": alignments,
        "prefix_validation": prefix_validation,
        "baseline": {},
        "m11_runs": [],
        "comparisons": {},
        "aggregate_comparison": None,
    }

    if args.offline_only:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True))
        print(json.dumps({"status": result["status"], "out": str(args.out)}, indent=2))
        return

    args.jsonl_out.parent.mkdir(parents=True, exist_ok=True)
    with args.jsonl_out.open("w") as jsonl:
        for task_id in [str(task) for task in args.tasks]:
            if prefix_validation.get(task_id, {}).get("status") != "ok":
                result["m11_runs"].append(
                    {
                        "task_id": task_id,
                        "status": "skipped",
                        "reason": "prefix validation failed",
                    }
                )
                continue
            selected_rows = rows_by_task[task_id][: args.trials]
            result["baseline"][task_id] = baseline_rows(selected_rows)
            for row in selected_rows:
                try:
                    run = run_one(row, alignments[task_id])
                except Exception as exc:
                    run = {
                        "task_id": task_id,
                        "trial": int(row["trial"]),
                        "seed": int(row["seed"]),
                        "status": "error",
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                result["m11_runs"].append(run)
                jsonl.write(json.dumps(run, sort_keys=True) + "\n")
                jsonl.flush()

    for task_id in [str(task) for task in args.tasks]:
        baseline = result["baseline"].get(task_id) or []
        m11 = [
            row
            for row in result["m11_runs"]
            if row.get("task_id") == task_id and row.get("status") == "ok"
        ]
        if baseline and m11:
            result["comparisons"][task_id] = compare_task(task_id, baseline, m11)

    if result["comparisons"]:
        baseline_all = []
        m11_all = []
        for task_id in result["comparisons"]:
            baseline_all.extend(result["baseline"][task_id])
            m11_all.extend(
                row
                for row in result["m11_runs"]
                if row.get("task_id") == task_id and row.get("status") == "ok"
            )
        result["aggregate_comparison"] = compare_task("aggregate", baseline_all, m11_all)
        result["status"] = "complete"
    else:
        result["status"] = "no_successful_runs"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps({"status": result["status"], "out": str(args.out)}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
