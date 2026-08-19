"""M6 validation gate for the M5.5 return NL boundary set.

This is a narrow experiment harness. It does not change the Haiku parser
prompt, does not change the M5 return executor, and does not build a router.
It replays the saved M5.5 Haiku outputs so M6 isolates the deterministic gate.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from m5_5_nl_boundary import CANONICAL_PRODUCT_NAMES, TEST_CASES
from m5_return_ladder import (
    Lookup,
    ReturnRequest,
    _call_group,
    _lookup_call,
    get_environment,
    run_self_resolved,
)
from tau2.utils.utils import get_now


WRITE_TOOL = "return_delivered_order_items"


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str
    stage: str
    derived_write_args: dict[str, Any] | None = None
    read_tool_calls: list[dict[str, Any]] | None = None


def _nonempty_strings(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _present_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def _schema_gate(parsed: dict[str, Any]) -> GateDecision | None:
    if not isinstance(parsed, dict):
        return GateDecision(False, "parse output is not a JSON object", "schema")

    status = str(parsed.get("status", "")).strip().upper()
    if status == "AMBIGUOUS/INSUFFICIENT":
        return GateDecision(False, "parser marked request ambiguous/insufficient", "schema")
    if status != "PARSED":
        return GateDecision(False, f"unsupported status: {status!r}", "schema")

    lookup = parsed.get("lookup")
    if not isinstance(lookup, dict):
        return GateDecision(False, "missing lookup object", "schema")

    method = lookup.get("method")
    values = lookup.get("values")
    if method == "email":
        if not isinstance(values, dict) or not values.get("email"):
            return GateDecision(False, "email lookup missing email", "schema")
    elif method == "name_zip":
        required = ("first_name", "last_name", "zip")
        if not isinstance(values, dict) or any(not values.get(key) for key in required):
            return GateDecision(False, "name_zip lookup missing first_name, last_name, or zip", "schema")
    else:
        return GateDecision(False, f"unsupported lookup method: {method!r}", "schema")

    return_items = parsed.get("return_item_names")
    keep_items = parsed.get("keep_item_names")
    has_return = _present_list(return_items)
    has_keep = _present_list(keep_items)
    if has_return and has_keep:
        return GateDecision(
            False,
            "contract violation: both return_item_names and keep_item_names populated",
            "schema",
        )
    if not has_return and not has_keep:
        return GateDecision(False, "missing return_item_names or keep_item_names", "schema")
    if has_return and not _nonempty_strings(return_items):
        return GateDecision(False, "return_item_names must be nonempty strings", "schema")
    if has_keep and not _nonempty_strings(keep_items):
        return GateDecision(False, "keep_item_names must be nonempty strings", "schema")

    catalog = set(CANONICAL_PRODUCT_NAMES)
    selected_names = return_items if has_return else keep_items
    unknown = sorted({name for name in selected_names if name not in catalog})
    if unknown:
        return GateDecision(
            False,
            f"unknown canonical product name(s): {', '.join(unknown)}",
            "schema",
        )

    payment_rule = parsed.get("payment_rule")
    if payment_rule not in (None, "original_payment_method"):
        return GateDecision(
            False,
            f"unsupported payment_rule: {payment_rule!r}",
            "schema",
        )

    return None


def _read_customer_orders(label: str, parsed: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    environment = get_environment()
    messages: list[Any] = []
    executed: list[dict[str, Any]] = []
    lookup = parsed["lookup"]
    lookup_name, lookup_args = _lookup_call(Lookup(lookup["method"], lookup["values"]))
    user_id = _call_group(environment, messages, executed, [(lookup_name, lookup_args)], label)[0]
    user = _call_group(
        environment,
        messages,
        executed,
        [("get_user_details", {"user_id": user_id})],
        label,
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
    return orders, executed


def _items_by_name(order: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in order["items"]:
        by_name.setdefault(item["name"], []).append(item)
    return by_name


def _catalog_gate(parsed: dict[str, Any], orders: list[dict[str, Any]]) -> GateDecision:
    return_names = parsed.get("return_item_names") or []
    keep_names = parsed.get("keep_item_names") or []
    candidates = []
    failures = []

    for order in orders:
        if order["status"] != "delivered":
            continue

        by_name = _items_by_name(order)
        if return_names:
            selected_items = []
            local_failures = []
            for name in return_names:
                matches = by_name.get(name, [])
                if len(matches) != 1:
                    local_failures.append(f"{name} resolved to {len(matches)} items")
                else:
                    selected_items.append(matches[0])
            if not local_failures:
                candidates.append((order, selected_items))
            else:
                failures.append(
                    f"{order['order_id']}: " + "; ".join(local_failures)
                )

        if keep_names:
            local_failures = []
            present_keep_names = []
            for name in keep_names:
                matches = by_name.get(name, [])
                if len(matches) > 1:
                    local_failures.append(f"{name} resolved to {len(matches)} items")
                elif len(matches) == 1:
                    present_keep_names.append(name)
            if not local_failures and present_keep_names:
                selected_items = [
                    item for item in order["items"] if item["name"] not in keep_names
                ]
                if selected_items:
                    candidates.append((order, selected_items))
                else:
                    failures.append(f"{order['order_id']}: keep list leaves no items to return")
            else:
                if not present_keep_names:
                    local_failures.append("no keep-list product found in this delivered order")
                failures.append(
                    f"{order['order_id']}: " + "; ".join(local_failures)
                )

    if len(candidates) != 1:
        detail = "; ".join(failures[:4])
        if len(failures) > 4:
            detail += f"; {len(failures) - 4} more order checks omitted"
        return GateDecision(
            False,
            f"catalog consistency failed: expected one unambiguous order/item match, got {len(candidates)}"
            + (f" ({detail})" if detail else ""),
            "catalog",
        )

    order, selected_items = candidates[0]
    return GateDecision(
        True,
        "schema and catalog consistency passed",
        "passed",
        {
            "order_id": order["order_id"],
            "item_ids": [item["item_id"] for item in selected_items],
            "payment_method_id": order["payment_history"][0]["payment_method_id"],
        },
    )


def run_gate(label: str, parsed: dict[str, Any]) -> GateDecision:
    schema_decision = _schema_gate(parsed)
    if schema_decision is not None:
        return schema_decision

    try:
        orders, read_tool_calls = _read_customer_orders(label, parsed)
    except Exception as exc:  # noqa: BLE001 - captured as gate outcome
        return GateDecision(False, f"read resolution failed: {type(exc).__name__}: {exc}", "read")

    catalog_decision = _catalog_gate(parsed, orders)
    return GateDecision(
        catalog_decision.allowed,
        catalog_decision.reason,
        catalog_decision.stage,
        catalog_decision.derived_write_args,
        read_tool_calls,
    )


def _request_from_parsed(task_id: str, parsed: dict[str, Any]) -> ReturnRequest:
    lookup = parsed["lookup"]
    return ReturnRequest(
        task_id=task_id,
        lookup=Lookup(lookup["method"], lookup["values"]),
        return_item_names=parsed.get("return_item_names"),
        keep_item_names=parsed.get("keep_item_names"),
        payment_rule=parsed.get("payment_rule") or "original_payment_method",
        parameter_source="M5.5 Haiku parsed output validated by M6 gate",
    )


def _has_write(script_result: dict[str, Any] | None) -> bool:
    if not script_result:
        return False
    return any(
        call["name"] == WRITE_TOOL for call in script_result.get("executed_tool_calls", [])
    )


def _run_case(case: Any, previous: dict[str, Any]) -> dict[str, Any]:
    parsed = previous["haiku"]["parsed_json"]
    gate_started_at = perf_counter()
    gate_start = get_now()
    decision = run_gate(f"m6_gate_{case.case_id}", parsed)
    gate_duration = perf_counter() - gate_started_at

    script_result = None
    script_error = None
    script_executed = False
    if decision.allowed:
        try:
            script_result = run_self_resolved(
                f"m6_execute_{case.case_id}",
                _request_from_parsed(case.task_id, parsed),
            )
            script_executed = True
        except Exception as exc:  # noqa: BLE001 - stored as experimental result
            script_error = f"{type(exc).__name__}: {exc}"
            script_executed = True

    verifier_pass = bool(script_result and script_result.get("pass") is True)
    write_executed = _has_write(script_result)
    wrong_write = bool(write_executed and not verifier_pass)

    previous_outcome = previous["outcome"]
    if decision.allowed and verifier_pass:
        outcome = "clean pass"
    elif wrong_write:
        outcome = "wrong write"
    elif not decision.allowed and previous_outcome == "clean pass":
        outcome = "over-defer"
    else:
        outcome = "correct deferral"

    return {
        "case_id": case.case_id,
        "task_id": case.task_id,
        "request_text": case.request_text,
        "m5_5_outcome": previous_outcome,
        "m5_5_wrong_write": previous["wrong_write"],
        "haiku": previous["haiku"],
        "gate": {
            "allowed": decision.allowed,
            "stage": decision.stage,
            "reason": decision.reason,
            "derived_write_args": decision.derived_write_args,
            "read_tool_calls": decision.read_tool_calls or [],
            "duration_seconds": gate_duration,
            "start_time": gate_start,
        },
        "script_executed": script_executed,
        "script_result": script_result,
        "script_error": script_error,
        "write_executed": write_executed,
        "verifier_pass": verifier_pass,
        "wrong_write": wrong_write,
        "outcome": outcome,
        "model_calls": 0,
        "gate_model_calls": 0,
        "script_tokens": 0,
        "script_cost_usd": 0.0,
    }


def _load_m5_5(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text())
    return {row["case_id"]: row for row in data["results"]}


def _m2_costs() -> dict[str, dict[str, float]]:
    root = Path(__file__).resolve().parents[1]
    rows = {}
    with (root / "metrics" / "m2_per_task_costs.csv").open() as f:
        for row in csv.DictReader(f):
            rows[row["task_id"]] = {
                "total_cached": float(row["total_cost_cached_usd"]),
            }

    m2_results = json.loads(
        (
            root
            / "tau-bench"
            / "data"
            / "simulations"
            / "sosog_m2_retail_db_checkable_cached_baseline"
            / "results.json"
        ).read_text()
    )
    for simulation in m2_results["simulations"]:
        task_id = str(simulation["task_id"])
        rows.setdefault(task_id, {})
        rows[task_id]["agent_cached"] = float(simulation["agent_cost"])
        rows[task_id]["user_cached"] = float(simulation["user_cost"])
    return rows


def _summarize(results: list[dict[str, Any]], m5_5: dict[str, dict[str, Any]]) -> dict[str, Any]:
    outcome_counts: dict[str, int] = {}
    for result in results:
        outcome_counts[result["outcome"]] = outcome_counts.get(result["outcome"], 0) + 1

    m2 = _m2_costs()
    haiku_cost = sum(row["haiku"]["cost_usd"] for row in m5_5.values())
    haiku_input_tokens = sum(row["haiku"]["usage"]["input_tokens"] for row in m5_5.values())
    haiku_output_tokens = sum(row["haiku"]["usage"]["output_tokens"] for row in m5_5.values())
    deferred = [row for row in results if row["outcome"] != "clean pass"]
    clean = [row for row in results if row["outcome"] == "clean pass"]
    all_agent = sum(m2[row["task_id"]]["agent_cached"] for row in results)
    all_total = sum(m2[row["task_id"]]["total_cached"] for row in results)
    fallback_agent = sum(m2[row["task_id"]]["agent_cached"] for row in deferred)
    fallback_total = sum(m2[row["task_id"]]["total_cached"] for row in deferred)
    previous_clean = [row for row in results if row["m5_5_outcome"] == "clean pass"]
    clean_survived = [
        row
        for row in results
        if row["m5_5_outcome"] == "clean pass" and row["outcome"] == "clean pass"
    ]
    previous_wrong = [row for row in results if row["m5_5_wrong_write"]]
    previous_wrong_now_deferred = [
        row
        for row in results
        if row["m5_5_wrong_write"] and row["outcome"] == "correct deferral"
    ]
    no_write_on_deferred = all(not row["write_executed"] for row in deferred)

    return {
        "request_count": len(results),
        "tasks": sorted({row["task_id"] for row in results}, key=int),
        "outcome_counts": outcome_counts,
        "wrong_writes": outcome_counts.get("wrong write", 0),
        "deterministically_handled": len(clean),
        "deterministically_handled_rate": len(clean) / len(results),
        "deferred": len(deferred),
        "deferred_rate": len(deferred) / len(results),
        "m5_5_clean_passes": len(previous_clean),
        "m5_5_clean_passes_survived": len(clean_survived),
        "over_defers": outcome_counts.get("over-defer", 0),
        "over_defer_rate_among_m5_5_clean_passes": outcome_counts.get("over-defer", 0)
        / len(previous_clean),
        "m5_5_wrong_writes": len(previous_wrong),
        "m5_5_wrong_writes_now_deferred": len(previous_wrong_now_deferred),
        "no_write_on_deferred": no_write_on_deferred,
        "model_calls": {
            "new_m6_model_calls": 0,
            "gate_model_calls": 0,
            "saved_m5_5_haiku_calls_replayed": len(m5_5),
        },
        "haiku_parse_cost_reused_from_m5_5": {
            "input_tokens": haiku_input_tokens,
            "output_tokens": haiku_output_tokens,
            "cost_usd": haiku_cost,
        },
        "cost": {
            "haiku_parse_plus_gate_execute_usd": haiku_cost,
            "fallback_agent_estimated_usd": fallback_agent,
            "tiered_with_gate_agent_only_estimated_usd": haiku_cost + fallback_agent,
            "all_sonnet_agent_only_estimated_usd": all_agent,
            "agent_only_savings_estimated_pct": (1 - (haiku_cost + fallback_agent) / all_agent)
            * 100,
            "fallback_benchmark_total_estimated_usd": fallback_total,
            "tiered_with_gate_benchmark_total_estimated_usd": haiku_cost + fallback_total,
            "all_sonnet_benchmark_total_estimated_usd": all_total,
            "benchmark_total_savings_estimated_pct": (1 - (haiku_cost + fallback_total) / all_total)
            * 100,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--m5-5-results",
        default=str(
            Path(__file__).resolve().parents[1]
            / "metrics"
            / "m5_5_nl_boundary_results.json"
        ),
    )
    parser.add_argument(
        "--out",
        default=str(
            Path(__file__).resolve().parents[1]
            / "metrics"
            / "m6_validation_gate_results.json"
        ),
    )
    args = parser.parse_args()

    m5_5 = _load_m5_5(Path(args.m5_5_results))
    results = []
    for case in TEST_CASES:
        result = _run_case(case, m5_5[case.case_id])
        results.append(result)
        print(
            json.dumps(
                {
                    "case_id": result["case_id"],
                    "task_id": result["task_id"],
                    "m5_5_outcome": result["m5_5_outcome"],
                    "m6_outcome": result["outcome"],
                    "gate_stage": result["gate"]["stage"],
                    "write_executed": result["write_executed"],
                    "wrong_write": result["wrong_write"],
                },
                sort_keys=True,
            )
        )

    output = {
        "summary": _summarize(results, m5_5),
        "results": results,
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
