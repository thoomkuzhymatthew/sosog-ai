"""M5 return-family generalization ladder.

This is a narrow experiment harness, not a general crystallization engine.
It runs local Retail tools and tau2's programmatic DB verifier only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import uuid4

from loguru import logger

logger.remove()

from tau2.data_model.message import AssistantMessage, ToolCall
from tau2.data_model.simulation import SimulationRun, TerminationReason
from tau2.domains.retail.environment import get_environment, get_tasks
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.utils.utils import get_now


@dataclass(frozen=True)
class Lookup:
    method: str
    values: dict[str, str]


@dataclass(frozen=True)
class ReturnParams:
    task_id: str
    lookup: Lookup
    user_id: str
    order_ids_to_read: list[str]
    product_ids_to_read: list[str]
    return_order_id: str
    return_item_ids: list[str]
    payment_method_id: str
    parameter_source: str


@dataclass(frozen=True)
class ReturnRequest:
    task_id: str
    lookup: Lookup
    return_item_names: list[str] | None = None
    keep_item_names: list[str] | None = None
    payment_rule: str = "original_payment_method"
    parameter_source: str = "structured task-level request"


TASK5_PARAMS = ReturnParams(
    task_id="5",
    lookup=Lookup(
        "name_zip", {"first_name": "Mei", "last_name": "Kovacs", "zip": "28236"}
    ),
    user_id="mei_kovacs_8020",
    order_ids_to_read=["#W6390527", "#W7800651", "#W8065207"],
    product_ids_to_read=["6817146515", "8310926033"],
    return_order_id="#W6390527",
    return_item_ids=["8538875209"],
    payment_method_id="paypal_7644869",
    parameter_source="M4 task 5 captured trace values",
)

TASK13_PARAMS = ReturnParams(
    task_id="13",
    lookup=Lookup("email", {"email": "mia.garcia2723@example.com"}),
    user_id="mia_garcia_4516",
    order_ids_to_read=["#W5490111", "#W7387996"],
    product_ids_to_read=[],
    return_order_id="#W5490111",
    return_item_ids=["4579334072", "6117189161", "4947717507"],
    payment_method_id="credit_card_3124723",
    parameter_source="task 13 evaluation_criteria.actions",
)

TASK48_PARAMS = ReturnParams(
    task_id="48",
    lookup=Lookup(
        "name_zip", {"first_name": "Daiki", "last_name": "Johnson", "zip": "80273"}
    ),
    user_id="daiki_johnson_9523",
    order_ids_to_read=["#W1436802", "#W5282037", "#W9502127"],
    product_ids_to_read=[],
    return_order_id="#W9502127",
    return_item_ids=["9534205511"],
    payment_method_id="paypal_2433177",
    parameter_source="task 48 evaluation_criteria.actions",
)

TASK13_REQUEST = ReturnRequest(
    task_id="13",
    lookup=Lookup("email", {"email": "mia.garcia2723@example.com"}),
    keep_item_names=["Mechanical Keyboard", "Gaming Mouse"],
    payment_rule="original_payment_method",
    parameter_source=(
        "task-level request: customer email; return everything except keyboard "
        "and mouse; refund via valid original method"
    ),
)

TASK48_REQUEST = ReturnRequest(
    task_id="48",
    lookup=Lookup(
        "name_zip", {"first_name": "Daiki", "last_name": "Johnson", "zip": "80273"}
    ),
    return_item_names=["Air Purifier"],
    payment_rule="original_payment_method",
    parameter_source=(
        "task-level request: customer name/zip; return the air purifier; "
        "refund on original method"
    ),
)


def _task(task_id: str):
    for task in get_tasks(task_split_name=None):
        if task.id == task_id:
            return task
    raise ValueError(f"Task {task_id} not found")


def _decode_tool_content(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def _lookup_call(lookup: Lookup) -> tuple[str, dict[str, str]]:
    if lookup.method == "email":
        return "find_user_id_by_email", lookup.values
    if lookup.method == "name_zip":
        return "find_user_id_by_name_zip", lookup.values
    raise ValueError(f"Unsupported lookup method: {lookup.method}")


def _call_group(environment, messages, executed, group, prefix: str):
    tool_calls = []
    for idx, (name, arguments) in enumerate(group):
        tool_call = ToolCall(
            id=f"{prefix}_{len(messages)}_{idx}",
            name=name,
            arguments=arguments,
            requestor="assistant",
        )
        tool_calls.append(tool_call)
        executed.append({"name": name, "arguments": arguments})

    messages.append(AssistantMessage(role="assistant", content="", tool_calls=tool_calls))
    responses = []
    for tool_call in tool_calls:
        response = environment.get_response(tool_call)
        if response.error:
            raise RuntimeError(
                f"Tool call failed: {tool_call.name} {tool_call.arguments} -> {response.content}"
            )
        messages.append(response)
        responses.append(_decode_tool_content(response.content))
    return responses


def _verify(task_id: str, messages: list, started_at: float, start: str) -> dict[str, Any]:
    reward_info = evaluate_simulation(
        simulation=SimulationRun(
            id=f"m5_return_{task_id}_{uuid4()}",
            task_id=task_id,
            start_time=start,
            end_time=get_now(),
            duration=perf_counter() - started_at,
            termination_reason=TerminationReason.AGENT_STOP,
            agent_cost=0.0,
            user_cost=0.0,
            messages=messages,
            trial=0,
            seed=0,
        ),
        task=_task(task_id),
        evaluation_type=EvaluationType.ENV,
        solo_mode=False,
        domain="retail",
        strict_replay=True,
    )
    return {
        "evaluation_type": EvaluationType.ENV.value,
        "reward": reward_info.reward,
        "db_match": reward_info.db_check.db_match if reward_info.db_check else None,
        "db_reward": reward_info.db_check.db_reward if reward_info.db_check else None,
        "reward_breakdown": {
            str(key.value if hasattr(key, "value") else key): value
            for key, value in (reward_info.reward_breakdown or {}).items()
        },
    }


def run_handfed(label: str, params: ReturnParams) -> dict[str, Any]:
    environment = get_environment()
    messages = []
    executed = []
    start = get_now()
    started_at = perf_counter()

    lookup_name, lookup_args = _lookup_call(params.lookup)
    _call_group(environment, messages, executed, [(lookup_name, lookup_args)], label)
    _call_group(
        environment,
        messages,
        executed,
        [("get_user_details", {"user_id": params.user_id})],
        label,
    )
    for order_id in params.order_ids_to_read:
        _call_group(
            environment,
            messages,
            executed,
            [("get_order_details", {"order_id": order_id})],
            label,
        )
    for product_id in params.product_ids_to_read:
        _call_group(
            environment,
            messages,
            executed,
            [("get_product_details", {"product_id": product_id})],
            label,
        )
    _call_group(
        environment,
        messages,
        executed,
        [
            (
                "return_delivered_order_items",
                {
                    "order_id": params.return_order_id,
                    "item_ids": params.return_item_ids,
                    "payment_method_id": params.payment_method_id,
                },
            )
        ],
        label,
    )

    verifier = _verify(params.task_id, messages, started_at, start)
    return {
        "label": label,
        "task_id": params.task_id,
        "pass": verifier["reward"] == 1.0 and verifier["db_match"] is True,
        "verifier": verifier,
        "model_calls": 0,
        "script_tokens": 0,
        "script_cost_usd": 0.0,
        "parameters_obtained": params.parameter_source,
        "derived_write_args": {
            "order_id": params.return_order_id,
            "item_ids": params.return_item_ids,
            "payment_method_id": params.payment_method_id,
        },
        "executed_tool_calls": executed,
    }


def run_self_resolved(label: str, request: ReturnRequest) -> dict[str, Any]:
    environment = get_environment()
    messages = []
    executed = []
    start = get_now()
    started_at = perf_counter()

    lookup_name, lookup_args = _lookup_call(request.lookup)
    user_id = _call_group(environment, messages, executed, [(lookup_name, lookup_args)], label)[0]
    user = _call_group(
        environment, messages, executed, [("get_user_details", {"user_id": user_id})], label
    )[0]

    orders = []
    for order_id in user["orders"]:
        order = _call_group(
            environment,
            messages,
            executed,
            [("get_order_details", {"order_id": order_id})],
            label,
        )[0]
        orders.append(order)

    return_names = {name.lower() for name in request.return_item_names or []}
    keep_names = {name.lower() for name in request.keep_item_names or []}
    candidates = []
    for order in orders:
        if order["status"] != "delivered":
            continue
        item_ids = []
        for item in order["items"]:
            item_name = item["name"].lower()
            if return_names and item_name in return_names:
                item_ids.append(item["item_id"])
            elif keep_names and item_name not in keep_names:
                item_ids.append(item["item_id"])
        if item_ids:
            candidates.append((order, item_ids))

    if len(candidates) != 1:
        raise RuntimeError(f"Expected one return candidate, got {len(candidates)}")

    order, item_ids = candidates[0]
    payment_method_id = order["payment_history"][0]["payment_method_id"]
    _call_group(
        environment,
        messages,
        executed,
        [
            (
                "return_delivered_order_items",
                {
                    "order_id": order["order_id"],
                    "item_ids": item_ids,
                    "payment_method_id": payment_method_id,
                },
            )
        ],
        label,
    )

    verifier = _verify(request.task_id, messages, started_at, start)
    return {
        "label": label,
        "task_id": request.task_id,
        "pass": verifier["reward"] == 1.0 and verifier["db_match"] is True,
        "verifier": verifier,
        "model_calls": 0,
        "script_tokens": 0,
        "script_cost_usd": 0.0,
        "parameters_obtained": request.parameter_source,
        "derived_write_args": {
            "order_id": order["order_id"],
            "item_ids": item_ids,
            "payment_method_id": payment_method_id,
        },
        "executed_tool_calls": executed,
    }


def main():
    results = [
        {
            "rung": "1",
            "description": "parameterized return script, same task 5 instance",
            "result": run_handfed("return_rung1_task5", TASK5_PARAMS),
        },
        {
            "rung": "2",
            "description": "same return procedure, hand-fed task 13 values",
            "result": run_handfed("return_rung2_task13", TASK13_PARAMS),
        },
        {
            "rung": "2",
            "description": "same return procedure, hand-fed task 48 values",
            "result": run_handfed("return_rung2_task48", TASK48_PARAMS),
        },
        {
            "rung": "3",
            "description": "same return procedure, self-resolved task 13 values",
            "result": run_self_resolved("return_rung3_task13", TASK13_REQUEST),
        },
        {
            "rung": "3",
            "description": "same return procedure, self-resolved task 48 values",
            "result": run_self_resolved("return_rung3_task48", TASK48_REQUEST),
        },
    ]
    print(json.dumps({"family": "return", "results": results}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
