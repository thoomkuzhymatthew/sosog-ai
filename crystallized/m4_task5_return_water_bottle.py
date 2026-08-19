"""M4 hand-built crystallization proof for Retail task 5.

This intentionally hardcodes one captured successful trace. It calls the
Retail tools directly and then asks tau2's local evaluator to score the
resulting message trajectory. There is no agent, user simulator, or LLM call.
"""

from __future__ import annotations

import json
from time import perf_counter
from uuid import uuid4

from loguru import logger

logger.remove()

from tau2.data_model.message import AssistantMessage, ToolCall
from tau2.data_model.simulation import SimulationRun, TerminationReason
from tau2.domains.retail.environment import get_environment, get_tasks
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.utils.utils import get_now

TASK_ID = "5"

# Captured by hand from:
# data/simulations/sosog_m3_retail_db_checkable_n10_cached/results.json
# task_id=5, trial=0.
TOOL_CALL_GROUPS = [
    [
        (
            "find_user_id_by_name_zip",
            {"first_name": "Mei", "last_name": "Kovacs", "zip": "28236"},
        )
    ],
    [("get_user_details", {"user_id": "mei_kovacs_8020"})],
    [
        ("get_order_details", {"order_id": "#W6390527"}),
        ("get_order_details", {"order_id": "#W7800651"}),
        ("get_order_details", {"order_id": "#W8065207"}),
    ],
    [
        ("get_product_details", {"product_id": "6817146515"}),
        ("get_product_details", {"product_id": "8310926033"}),
    ],
    [
        (
            "return_delivered_order_items",
            {
                "order_id": "#W6390527",
                "item_ids": ["8538875209"],
                "payment_method_id": "paypal_7644869",
            },
        )
    ],
]


def _task():
    for task in get_tasks(task_split_name=None):
        if task.id == TASK_ID:
            return task
    raise ValueError(f"Task {TASK_ID} not found")


def build_crystallized_trajectory():
    """Execute the fixed tool-call sequence and record tau2 message objects."""
    environment = get_environment()
    messages = []
    executed_actions = []

    for group_idx, group in enumerate(TOOL_CALL_GROUPS):
        tool_calls = []
        for call_idx, (name, arguments) in enumerate(group):
            tool_call = ToolCall(
                id=f"m4_task5_g{group_idx}_c{call_idx}",
                name=name,
                arguments=arguments,
                requestor="assistant",
            )
            tool_calls.append(tool_call)
            executed_actions.append({"name": name, "arguments": arguments})

        messages.append(AssistantMessage(role="assistant", content="", tool_calls=tool_calls))
        for tool_call in tool_calls:
            response = environment.get_response(tool_call)
            if response.error:
                raise RuntimeError(
                    f"Tool call failed: {tool_call.name} {tool_call.arguments} -> {response.content}"
                )
            messages.append(response)

    return messages, executed_actions


def main():
    task = _task()
    start = get_now()
    started_at = perf_counter()
    messages, executed_actions = build_crystallized_trajectory()
    end = get_now()

    simulation = SimulationRun(
        id=f"m4_task5_{uuid4()}",
        task_id=TASK_ID,
        start_time=start,
        end_time=end,
        duration=perf_counter() - started_at,
        termination_reason=TerminationReason.AGENT_STOP,
        agent_cost=0.0,
        user_cost=0.0,
        messages=messages,
        trial=0,
        seed=0,
    )

    reward_info = evaluate_simulation(
        simulation=simulation,
        task=task,
        evaluation_type=EvaluationType.ENV,
        solo_mode=False,
        domain="retail",
        strict_replay=True,
    )
    simulation.reward_info = reward_info

    output = {
        "task_id": TASK_ID,
        "source_trace": "sosog_m3_retail_db_checkable_n10_cached task_id=5 trial=0",
        "executed_tool_calls": executed_actions,
        "script_tokens": 0,
        "script_cost_usd": 0.0,
        "model_calls": 0,
        "verifier": {
            "evaluation_type": EvaluationType.ENV.value,
            "reward": reward_info.reward,
            "db_match": reward_info.db_check.db_match if reward_info.db_check else None,
            "db_reward": reward_info.db_check.db_reward if reward_info.db_check else None,
            "reward_breakdown": {
                str(key.value if hasattr(key, "value") else key): value
                for key, value in (reward_info.reward_breakdown or {}).items()
            },
        },
        "honesty_checks": {
            "made_model_calls": False,
            "executed_workflow_tool_sequence": True,
            "hardcoded_to_exact_task_instance": True,
        },
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
