#!/usr/bin/env python3
"""M11 scale harness for the remaining decomposition candidates.

This extends the task-97 live A/B pattern to tasks 30, 87, 100, and 112.
Each decomposed run scripts only the deterministic read-only prefix from the
M11 alignment result, then delegates the volatile tail to the stock Sonnet
agent. Baseline and decomposed arms are interleaved by task and seed.
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
)
from tau2.data_model.simulation import TextRunConfig  # noqa: E402
from tau2.domains.retail.environment import get_tasks  # noqa: E402
from tau2.evaluator.evaluator import EvaluationType  # noqa: E402
from tau2.registry import registry  # noqa: E402
from tau2.runner.build import build_text_orchestrator  # noqa: E402
from tau2.runner.simulation import run_simulation  # noqa: E402


SOSOG_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "bedrock/us.anthropic.claude-sonnet-4-6"
MODEL = os.environ.get("M11_SCALE_MODEL", DEFAULT_MODEL)
ALIGNMENT_JSON = SOSOG_ROOT / "metrics" / "m11_decomposition_results.json"
OUT_JSON = SOSOG_ROOT / "metrics" / "m11_scale_results.json"
OUT_JSONL = SOSOG_ROOT / "traces" / "m11" / "scale_ab.jsonl"

DEFAULT_TASKS = ["30", "87", "100", "112"]
SEEDS = [
    1103001,
    1103019,
    1103037,
    1103061,
    1103079,
    1103091,
    1103123,
    1103153,
    1103181,
    1103213,
    1103241,
    1103267,
    1103303,
    1103337,
    1103361,
    1103397,
    1103421,
    1103451,
    1103477,
    1103511,
]

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
PREFIX_CALLS_BY_TASK: dict[str, list[dict[str, Any]]] = {}


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


def load_prefix_calls(task_ids: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    data = json.loads(ALIGNMENT_JSON.read_text())
    alignment = data["alignment"]
    prefix_validation = data["prefix_validation"]
    calls_by_task: dict[str, list[dict[str, Any]]] = {}
    for task_id in task_ids:
        if task_id not in alignment:
            raise ValueError(f"Task {task_id} missing from M11 alignment")
        validation = prefix_validation.get(task_id) or {}
        if validation.get("status") != "ok":
            raise ValueError(f"Task {task_id} prefix validation is not ok")
        calls = alignment[task_id]["safe_prefix_calls"]
        if not calls:
            raise ValueError(f"Task {task_id} has no safe prefix calls")
        for call in calls:
            if call["name"] not in READ_TOOLS or call["name"] in WRITE_TOOLS:
                raise ValueError(f"Task {task_id} has unsafe prefix call {call['name']}")
        calls_by_task[task_id] = [
            {"name": call["name"], "arguments": call["arguments"]}
            for call in calls
        ]
    return calls_by_task, {
        task_id: {
            "alignment": alignment[task_id],
            "prefix_validation": {
                "status": prefix_validation[task_id]["status"],
                "trace_hashes_match_prefix": prefix_validation[task_id][
                    "validation"
                ]["trace_hashes_match_prefix"],
                "deterministic_two_fresh_executions": prefix_validation[task_id][
                    "validation"
                ]["deterministic_two_fresh_executions"],
                "gate_caught_corruption": prefix_validation[task_id]["validation"][
                    "gate_caught_corruption"
                ],
            },
        }
        for task_id in task_ids
    }


class M11ScaleState(LLMAgentState):
    prefix_index: int = 0
    auth_prompted: bool = False
    handed_to_llm: bool = False
    prefix_results: list[dict[str, Any]] = Field(default_factory=list)


class M11ScaleDecomposedAgent(LLMAgent):
    def __init__(self, *args, task_id: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.task_id = task_id
        self.prefix_calls = PREFIX_CALLS_BY_TASK[task_id]

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
        return M11ScaleState(
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

    def _append_input(self, message: Message, state: M11ScaleState) -> None:
        if isinstance(message, MultiToolMessage):
            state.messages.extend(message.tool_messages)
            for tool_message in message.tool_messages:
                self._record_prefix_result(tool_message, state)
            return
        state.messages.append(message)
        if isinstance(message, ToolMessage):
            self._record_prefix_result(message, state)

    def _record_prefix_result(
        self, message: ToolMessage, state: M11ScaleState
    ) -> None:
        if len(state.prefix_results) >= len(self.prefix_calls):
            return
        expected = self.prefix_calls[len(state.prefix_results)]
        if message.error:
            raise ValueError(f"Prefix tool errored: {expected['name']}")
        shape_check(expected["name"], message.content)
        state.prefix_results.append(
            {
                "name": expected["name"],
                "arguments": expected["arguments"],
                "content": message.content,
                "error": message.error,
            }
        )

    def _prefix_tool_message(self, state: M11ScaleState) -> AssistantMessage:
        call = self.prefix_calls[state.prefix_index]
        if call["name"] not in READ_TOOLS or call["name"] in WRITE_TOOLS:
            raise ValueError(f"Unsafe scripted prefix call: {call['name']}")
        state.prefix_index += 1
        return AssistantMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id=(
                        f"m11scale_{self.task_id}_{state.prefix_index}_"
                        f"{uuid4().hex[:8]}"
                    ),
                    name=call["name"],
                    arguments=call["arguments"],
                    requestor="assistant",
                )
            ],
            cost=0.0,
            usage=None,
        )

    def generate_next_message(
        self, message: Message, state: M11ScaleState
    ) -> tuple[AssistantMessage, M11ScaleState]:
        if state.handed_to_llm:
            return super().generate_next_message(message, state)

        if not state.auth_prompted:
            self._append_input(message, state)
            assistant_message = AssistantMessage(
                role="assistant",
                content=(
                    "I can help with that. First I need to verify your identity. "
                    "Could you provide your email address, or your name and ZIP code?"
                ),
                cost=0.0,
                usage=None,
            )
            state.auth_prompted = True
            state.messages.append(assistant_message)
            return assistant_message, state

        if state.prefix_index < len(self.prefix_calls):
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


def create_m11_scale_decomposed_agent(tools, domain_policy, **kwargs):
    return M11ScaleDecomposedAgent(
        tools=tools,
        domain_policy=domain_policy,
        llm=kwargs.get("llm"),
        llm_args=kwargs.get("llm_args"),
        task_id=CURRENT_TASK_ID,
    )


def ensure_registered() -> None:
    if registry.get_agent_factory("m11_scale_decomposed_agent") is None:
        registry.register_agent_factory(
            create_m11_scale_decomposed_agent, "m11_scale_decomposed_agent"
        )


def get_task(task_id: str):
    for task in get_tasks(task_split_name=None):
        if str(task.id) == str(task_id):
            return task
    raise ValueError(f"Task {task_id} not found")


def make_config(arm: str) -> TextRunConfig:
    agent = "llm_agent" if arm == "baseline" else "m11_scale_decomposed_agent"
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
    config = make_config(arm)
    task = get_task(task_id)
    orchestrator = build_text_orchestrator(
        config,
        task,
        seed=seed,
        simulation_id=f"m11_scale_{task_id}_{arm}_{trial}_{seed}_{uuid4()}",
    )
    simulation = run_simulation(orchestrator, evaluation_type=EvaluationType.ENV)
    simulation.trial = trial
    sim_json = simulation.model_dump(mode="json")
    messages = sim_json.get("messages") or []
    usage_by_role = role_usage_for_messages(messages)
    total_usage = flatten_usage(usage_by_role)
    reward_info = sim_json.get("reward_info") or {}
    db_check = reward_info.get("db_check") or {}
    prefix_results = []
    if arm == "decomposed":
        agent_state = getattr(orchestrator, "agent_state", None)
        prefix_results = list(getattr(agent_state, "prefix_results", []) or [])
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
        "prefix_expected_count": len(PREFIX_CALLS_BY_TASK.get(task_id, [])),
        "prefix_results_count": len(prefix_results),
        "prefix_model_calls": 0 if arm == "decomposed" else None,
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


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out.pop("messages", None)
    return out


def resume_key(row: dict[str, Any]) -> tuple[str, str, int] | None:
    task_id = row.get("task_id")
    arm = row.get("arm")
    trial = row.get("trial")
    if task_id is None or arm not in {"baseline", "decomposed"} or trial is None:
        return None
    return (str(task_id), str(arm), int(trial))


def load_resume_rows(
    path: Path, task_ids: list[str], n: int
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
            if row.get("status") == "ok":
                row.setdefault("model", DEFAULT_MODEL)
                by_key[key] = row

    rows = sorted(by_key.values(), key=lambda row: (row["trial"], row["task_id"], row["arm"]))
    return rows, set(by_key)


def load_summary_rows(path: Path, task_ids: list[str], n: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []

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
            row.setdefault("model", DEFAULT_MODEL)
            by_key[key] = row

    return sorted(by_key.values(), key=lambda row: (row["trial"], row["task_id"], row["arm"]))


def build_result(
    rows: list[dict[str, Any]], args: argparse.Namespace, prefix_metadata: dict[str, Any]
) -> dict[str, Any]:
    task_summaries: dict[str, Any] = {}
    for task_id in args.tasks:
        task_rows = [row for row in rows if row.get("task_id") == task_id]
        by_arm = {
            arm: [row for row in task_rows if row.get("arm") == arm]
            for arm in ["baseline", "decomposed"]
        }
        summaries = {arm: summarize(arm_rows) for arm, arm_rows in by_arm.items()}
        baseline = summaries["baseline"]
        decomposed = summaries["decomposed"]
        pass_rate_delta = decomposed["pass_rate"] - baseline["pass_rate"]
        task_summaries[task_id] = {
            "summaries": summaries,
            "pass_rate_delta_decomposed_minus_baseline": pass_rate_delta,
            "pass_rate_preserved": (
                baseline["runs"] > 0
                and decomposed["runs"] > 0
                and decomposed["pass_rate"] >= baseline["pass_rate"]
            ),
            "total_token_saved": baseline["usage_total"]["total_tokens"]
            - decomposed["usage_total"]["total_tokens"],
            "agent_token_saved": baseline["usage_agent"]["total_tokens"]
            - decomposed["usage_agent"]["total_tokens"],
            "total_cost_saved_cached_usd": baseline["cost_total_cached_usd"]
            - decomposed["cost_total_cached_usd"],
            "agent_cost_saved_cached_usd": baseline["cost_agent_cached_usd"]
            - decomposed["cost_agent_cached_usd"],
            "prefix_expected_count": len(PREFIX_CALLS_BY_TASK[task_id]),
            "prefix_safety_violations": [
                compact_row(row)
                for row in by_arm["decomposed"]
                if row.get("status") == "ok"
                and (
                    row.get("prefix_results_count")
                    != len(PREFIX_CALLS_BY_TASK[task_id])
                    or row.get("prefix_model_calls") != 0
                )
            ],
        }

    all_baseline = [row for row in rows if row.get("arm") == "baseline"]
    all_decomposed = [row for row in rows if row.get("arm") == "decomposed"]
    aggregate_baseline = summarize(all_baseline)
    aggregate_decomposed = summarize(all_decomposed)
    return {
        "status": "complete",
        "model": MODEL,
        "models_seen": sorted(
            {
                row.get("model") or DEFAULT_MODEL
                for row in rows
                if row.get("status") == "ok"
            }
        ),
        "tasks": args.tasks,
        "n_requested_per_task_per_arm": args.n,
        "seeds": SEEDS[: args.n],
        "config": {
            "temperature": 0.0,
            "prompt_cache_env": "TAU2_BEDROCK_PROMPT_CACHE",
            "baseline_agent": "llm_agent",
            "decomposed_agent": "m11_scale_decomposed_agent",
            "user": "user_simulator",
        },
        "prefix_metadata": prefix_metadata,
        "task_summaries": task_summaries,
        "aggregate": {
            "baseline": aggregate_baseline,
            "decomposed": aggregate_decomposed,
            "pass_rate_preserved": (
                aggregate_baseline["runs"] > 0
                and aggregate_decomposed["runs"] > 0
                and aggregate_decomposed["pass_rate"] >= aggregate_baseline["pass_rate"]
            ),
            "total_token_saved": aggregate_baseline["usage_total"]["total_tokens"]
            - aggregate_decomposed["usage_total"]["total_tokens"],
            "agent_token_saved": aggregate_baseline["usage_agent"]["total_tokens"]
            - aggregate_decomposed["usage_agent"]["total_tokens"],
            "total_cost_saved_cached_usd": aggregate_baseline[
                "cost_total_cached_usd"
            ]
            - aggregate_decomposed["cost_total_cached_usd"],
            "agent_cost_saved_cached_usd": aggregate_baseline[
                "cost_agent_cached_usd"
            ]
            - aggregate_decomposed["cost_agent_cached_usd"],
        },
        "runs": [compact_row(row) for row in rows],
    }


def main() -> None:
    global MODEL
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", nargs="+", default=DEFAULT_TASKS)
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--out", type=Path, default=OUT_JSON)
    parser.add_argument("--jsonl-out", type=Path, default=OUT_JSONL)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Append to an existing JSONL and skip completed ok task/arm/trial rows.",
    )
    parser.add_argument(
        "--summarize-only",
        action="store_true",
        help="Rebuild the metrics JSON from JSONL without running missing rows.",
    )
    args = parser.parse_args()

    MODEL = args.model

    if args.n > len(SEEDS):
        raise ValueError(f"Only {len(SEEDS)} fixed seeds are defined")

    ensure_registered()
    global PREFIX_CALLS_BY_TASK
    PREFIX_CALLS_BY_TASK, prefix_metadata = load_prefix_calls(args.tasks)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.jsonl_out.parent.mkdir(parents=True, exist_ok=True)

    if args.summarize_only:
        rows = load_summary_rows(args.jsonl_out, args.tasks, args.n)
        result = build_result(rows, args, prefix_metadata)
        target_rows = len(args.tasks) * 2 * args.n
        ok_rows = len([row for row in rows if row.get("status") == "ok"])
        error_rows = [row for row in rows if row.get("status") != "ok"]
        if ok_rows < target_rows or error_rows:
            result["status"] = "blocked_or_partial"
            if error_rows:
                result["blocker"] = error_rows[-1].get("error")
            else:
                result["blocker"] = (
                    f"summarize-only corpus has {ok_rows}/{target_rows} ok rows"
                )
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True))
        print(json.dumps({"status": result["status"], "out": str(args.out)}, indent=2))
        return

    rows: list[dict[str, Any]]
    completed: set[tuple[str, str, int]]
    if args.resume:
        rows, completed = load_resume_rows(args.jsonl_out, args.tasks, args.n)
    else:
        rows, completed = [], set()

    mode = "a" if args.resume else "w"
    with args.jsonl_out.open(mode) as jsonl:
        for trial, seed in enumerate(SEEDS[: args.n]):
            for task_id in args.tasks:
                task_seed = seed + int(task_id)
                for arm in ["baseline", "decomposed"]:
                    key = (str(task_id), arm, trial)
                    if key in completed:
                        continue
                    started = time.perf_counter()
                    try:
                        row = run_one(task_id, arm, task_seed, trial)
                    except Exception as exc:
                        elapsed_s = time.perf_counter() - started
                        row = {
                            "arm": arm,
                            "task_id": task_id,
                            "trial": trial,
                            "seed": task_seed,
                            "status": "error",
                            "model": MODEL,
                            "error": str(exc),
                            "traceback": traceback.format_exc(),
                            "elapsed_s": elapsed_s,
                        }
                        rows.append(row)
                        jsonl.write(json.dumps(row, sort_keys=True) + "\n")
                        jsonl.flush()
                        result = build_result(rows, args, prefix_metadata)
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

    result = build_result(rows, args, prefix_metadata)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps({"status": result["status"], "out": str(args.out)}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
