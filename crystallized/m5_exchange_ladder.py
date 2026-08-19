"""M5 exchange-family generalization ladder.

This is a narrow experiment harness for the exchange subgroup
6/7/8/9/58. It runs local Retail tools and tau2's programmatic DB verifier
only; it is not a router or general engine.
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
class ExchangeParams:
    task_id: str
    lookup: Lookup
    user_id: str
    order_id: str
    product_ids_to_read: list[str]
    item_ids: list[str]
    new_item_ids: list[str]
    payment_method_id: str
    parameter_source: str


@dataclass(frozen=True)
class ExchangeRequest:
    task_id: str
    lookup: Lookup
    inspect_item_names: list[str]
    exchange_item_names: list[str]
    desired_options: dict[str, dict[str, str]]
    option_preferences: dict[str, dict[str, list[str]]]
    payment_rule: str = "original_payment_method"
    parameter_source: str = "structured task-level request"


TASK8_PARAMS = ExchangeParams(
    task_id="8",
    lookup=Lookup(
        "name_zip", {"first_name": "Mei", "last_name": "Kovacs", "zip": "28236"}
    ),
    user_id="mei_kovacs_8020",
    order_id="#W6390527",
    product_ids_to_read=["8310926033", "6817146515"],
    item_ids=["8384507844"],
    new_item_ids=["9083642334"],
    payment_method_id="paypal_7644869",
    parameter_source="task 8 evaluation_criteria.actions",
)

TASK8_REQUEST = ExchangeRequest(
    task_id="8",
    lookup=Lookup(
        "name_zip", {"first_name": "Mei", "last_name": "Kovacs", "zip": "28236"}
    ),
    inspect_item_names=["Water Bottle", "Desk Lamp"],
    exchange_item_names=["Desk Lamp"],
    desired_options={"Desk Lamp": {"brightness": "high"}},
    option_preferences={"Desk Lamp": {"power source": ["battery", "USB", "AC adapter"]}},
    payment_rule="original_payment_method",
    parameter_source=(
        "task-level request: customer name/zip; inspect water bottle and desk lamp; "
        "after confirmation exchange only the desk lamp to a brighter one, "
        "preferring battery then USB then AC"
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
    if lookup.method == "name_zip":
        return "find_user_id_by_name_zip", lookup.values
    if lookup.method == "email":
        return "find_user_id_by_email", lookup.values
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
            id=f"m5_exchange_{task_id}_{uuid4()}",
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


def run_handfed(label: str, params: ExchangeParams) -> dict[str, Any]:
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
    _call_group(
        environment,
        messages,
        executed,
        [("get_order_details", {"order_id": params.order_id})],
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
                "exchange_delivered_order_items",
                {
                    "order_id": params.order_id,
                    "item_ids": params.item_ids,
                    "new_item_ids": params.new_item_ids,
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
            "order_id": params.order_id,
            "item_ids": params.item_ids,
            "new_item_ids": params.new_item_ids,
            "payment_method_id": params.payment_method_id,
        },
        "executed_tool_calls": executed,
    }


def _score_variant(variant: dict[str, Any], desired: dict[str, str], prefs: dict[str, list[str]]):
    if not variant["available"]:
        return None
    options = variant["options"]
    for key, value in desired.items():
        if options.get(key) != value:
            return None
    score = []
    for key, values in prefs.items():
        option_value = options.get(key)
        score.append(values.index(option_value) if option_value in values else len(values))
    score.append(variant["price"])
    score.append(variant["item_id"])
    return tuple(score)


def run_self_resolved(label: str, request: ExchangeRequest) -> dict[str, Any]:
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

    inspected = []
    inspect_names = {name.lower() for name in request.inspect_item_names}
    for order_id in user["orders"]:
        order = _call_group(
            environment,
            messages,
            executed,
            [("get_order_details", {"order_id": order_id})],
            label,
        )[0]
        if order["status"] != "delivered":
            continue
        names = {item["name"].lower() for item in order["items"]}
        if inspect_names.issubset(names):
            inspected.append(order)

    if len(inspected) != 1:
        raise RuntimeError(f"Expected one exchange order candidate, got {len(inspected)}")

    order = inspected[0]
    product_by_item_name = {}
    product_ids = []
    for item_name in request.inspect_item_names:
        item = next(item for item in order["items"] if item["name"].lower() == item_name.lower())
        product = _call_group(
            environment,
            messages,
            executed,
            [("get_product_details", {"product_id": item["product_id"]})],
            label,
        )[0]
        product_by_item_name[item_name.lower()] = product
        product_ids.append(item["product_id"])

    item_ids = []
    new_item_ids = []
    for item_name in request.exchange_item_names:
        old_item = next(
            item for item in order["items"] if item["name"].lower() == item_name.lower()
        )
        product = product_by_item_name[item_name.lower()]
        desired = request.desired_options.get(item_name, {})
        prefs = request.option_preferences.get(item_name, {})
        scored = []
        for variant in product["variants"].values():
            if variant["item_id"] == old_item["item_id"]:
                continue
            score = _score_variant(variant, desired, prefs)
            if score is not None:
                scored.append((score, variant))
        if not scored:
            raise RuntimeError(f"No variant matched request for {item_name}")
        scored.sort(key=lambda row: row[0])
        item_ids.append(old_item["item_id"])
        new_item_ids.append(scored[0][1]["item_id"])

    payment_method_id = order["payment_history"][0]["payment_method_id"]
    _call_group(
        environment,
        messages,
        executed,
        [
            (
                "exchange_delivered_order_items",
                {
                    "order_id": order["order_id"],
                    "item_ids": item_ids,
                    "new_item_ids": new_item_ids,
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
            "new_item_ids": new_item_ids,
            "payment_method_id": payment_method_id,
        },
        "product_ids_read_for_exchange": product_ids,
        "executed_tool_calls": executed,
    }


def main():
    results = [
        {
            "rung": "4.2",
            "description": "exchange procedure, hand-fed task 8 values",
            "source_task": "6",
            "holdout_task": "8",
            "result": run_handfed("exchange_rung4_handfed_task8", TASK8_PARAMS),
        },
        {
            "rung": "4.3",
            "description": "exchange procedure, self-resolved task 8 values",
            "source_task": "6",
            "holdout_task": "8",
            "result": run_self_resolved("exchange_rung4_self_resolved_task8", TASK8_REQUEST),
        },
    ]
    print(json.dumps({"family": "exchange", "results": results}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
