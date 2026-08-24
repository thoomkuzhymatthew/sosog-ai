#!/usr/bin/env python3
"""Independent final evaluation for the M18 Flight-change repair experiment."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any
from uuid import uuid4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--tau-root", required=True, type=Path)
    parser.add_argument("--proposal", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args()


def load_proposal(path: Path):
    name = "crystallized.airline.flight_change"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import proposal: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


class RecordingTools:
    def __init__(self, environment, assistant_message, tool_call):
        self.environment = environment
        self.assistant_message = assistant_message
        self.tool_call = tool_call
        self.messages: list[Any] = []
        self.calls: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        call = {"name": name, "arguments": deepcopy(arguments)}
        self.calls.append(call)
        if name == "update_reservation_flights":
            self.writes.append(call)
        tool_call = self.tool_call(
            id=f"repair_controller_{len(self.calls)}",
            name=name,
            arguments=deepcopy(arguments),
            requestor="assistant",
        )
        self.messages.append(
            self.assistant_message(role="assistant", content="", tool_calls=[tool_call])
        )
        response = self.environment.get_response(tool_call)
        self.messages.append(response)
        if response.error:
            raise RuntimeError(response.content)
        try:
            return json.loads(response.content)
        except json.JSONDecodeError:
            return response.content


class SyntheticTools:
    def __init__(self, fixture: dict[str, Any]):
        self.reservation = deepcopy(fixture["reservation"])
        self.user = deepcopy(fixture["user"])
        self.searches = deepcopy(fixture["searches"])
        self.statuses = deepcopy(fixture.get("statuses", {}))
        self.calls: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        call = {"name": name, "arguments": deepcopy(arguments)}
        self.calls.append(call)
        if name == "get_reservation_details":
            return deepcopy(self.reservation)
        if name == "get_user_details":
            return deepcopy(self.user)
        if name == "get_flight_status":
            key = (arguments["flight_number"], arguments["date"])
            return self.statuses.get(key, "available")
        if name == "search_direct_flight":
            key = (arguments["origin"], arguments["destination"], arguments["date"])
            return deepcopy(self.searches.get(key, []))
        if name == "update_reservation_flights":
            self.writes.append(call)
            self.reservation["cabin"] = arguments["cabin"]
            flight_map = {
                (item["flight_number"], search_key[2]): item
                for search_key, values in self.searches.items()
                for item in values
            }
            current_map = {
                (item["flight_number"], item["date"]): item
                for item in self.reservation["flights"]
            }
            updated = []
            for requested in arguments["flights"]:
                key = (requested["flight_number"], requested["date"])
                source = flight_map.get(key, current_map.get(key))
                if source is None:
                    raise RuntimeError(f"synthetic flight missing: {key}")
                updated.append(
                    {
                        "flight_number": requested["flight_number"],
                        "date": requested["date"],
                        "origin": source["origin"],
                        "destination": source["destination"],
                        "price": source.get("prices", {}).get(
                            arguments["cabin"], source.get("price", 0)
                        ),
                    }
                )
            self.reservation["flights"] = updated
            return deepcopy(self.reservation)
        raise RuntimeError(f"unexpected synthetic tool: {name}")


def flight_intent(task: dict[str, Any], raw_db: dict[str, Any]) -> dict[str, Any]:
    action = next(
        action
        for action in task["evaluation_criteria"]["actions"]
        if action["name"] == "update_reservation_flights"
    )["arguments"]
    reservation = raw_db["reservations"][action["reservation_id"]]
    flights = []
    for requested in action["flights"]:
        flight = raw_db["flights"][requested["flight_number"]]
        flights.append(
            {
                "flight_number": requested["flight_number"],
                "date": requested["date"],
                "origin": flight["origin"],
                "destination": flight["destination"],
            }
        )
    return {
        "user_id": reservation["user_id"],
        "reservation_id": action["reservation_id"],
        "cabin": action["cabin"],
        "flights": flights,
        "payment_id": action["payment_id"],
        "confirmed": True,
    }


def candidate(number: str, origin: str, destination: str, prices: dict[str, int]):
    return {
        "flight_number": number,
        "origin": origin,
        "destination": destination,
        "status": "available",
        "available_seats": {"basic_economy": 8, "economy": 8, "business": 8},
        "prices": prices,
    }


def base_fixture(
    *,
    cabin: str = "economy",
    old_number: str = "SYN101",
    old_origin: str = "AUS",
    old_destination: str = "RDU",
    old_price: int = 200,
    payment_source: str = "credit_card",
    payment_amount: float | None = None,
) -> dict[str, Any]:
    payment = {"source": payment_source, "id": "pay_synthetic_1"}
    if payment_amount is not None:
        payment["amount"] = payment_amount
    return {
        "reservation": {
            "reservation_id": "SYN001",
            "user_id": "user_synthetic_1",
            "origin": old_origin,
            "destination": old_destination,
            "flight_type": "one_way",
            "cabin": cabin,
            "flights": [
                {
                    "flight_number": old_number,
                    "date": "2024-06-10",
                    "origin": old_origin,
                    "destination": old_destination,
                    "price": old_price,
                }
            ],
            "passengers": [
                {"first_name": "Nora", "last_name": "Stone", "dob": "1988-02-14"}
            ],
            "status": None,
        },
        "user": {
            "user_id": "user_synthetic_1",
            "reservations": ["SYN001"],
            "payment_methods": {"pay_synthetic_1": payment},
        },
        "searches": {},
    }


def intent(
    flights: list[dict[str, str]],
    *,
    cabin: str = "economy",
    user_id: str = "user_synthetic_1",
    payment_id: str = "pay_synthetic_1",
    confirmed: bool = True,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "reservation_id": "SYN001",
        "cabin": cabin,
        "flights": flights,
        "payment_id": payment_id,
        "confirmed": confirmed,
    }


def synthetic_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    fixture = base_fixture(cabin="business", old_price=500, payment_source="gift_card", payment_amount=0.0)
    fixture["searches"][("AUS", "RDU", "2024-06-10")] = [
        candidate("SYN101", "AUS", "RDU", {"basic_economy": 80, "economy": 120, "business": 500})
    ]
    cases.append({
        "case_id": "normal-gift-card-refund-with-float-balance",
        "fixture": fixture,
        "intent": intent([{"flight_number": "SYN101", "date": "2024-06-10", "origin": "AUS", "destination": "RDU"}], cabin="economy"),
        "expected_status": "COMPLETED",
        "expected_writes": 1,
    })

    fixture = base_fixture(cabin="economy", old_price=100, payment_source="gift_card", payment_amount=80.0)
    fixture["searches"][("AUS", "RDU", "2024-06-10")] = [
        candidate("SYN101", "AUS", "RDU", {"basic_economy": 70, "economy": 100, "business": 180})
    ]
    cases.append({
        "case_id": "normal-exact-gift-card-charge-with-float-balance",
        "fixture": fixture,
        "intent": intent([{"flight_number": "SYN101", "date": "2024-06-10", "origin": "AUS", "destination": "RDU"}], cabin="business"),
        "expected_status": "COMPLETED",
        "expected_writes": 1,
    })

    fixture = base_fixture()
    fixture["searches"][("AUS", "RDU", "2024-06-11")] = [
        candidate("SYN202", "AUS", "RDU", {"basic_economy": 90, "economy": 210, "business": 410})
    ]
    cases.append({
        "case_id": "normal-credit-card-route-date-change",
        "fixture": fixture,
        "intent": intent([{"flight_number": "SYN202", "date": "2024-06-11", "origin": "AUS", "destination": "RDU"}]),
        "expected_status": "COMPLETED",
        "expected_writes": 1,
    })

    fixture = base_fixture(old_destination="BOS")
    fixture["reservation"]["destination"] = "BOS"
    fixture["searches"][("AUS", "ORD", "2024-06-12")] = [
        candidate("SYN301", "AUS", "ORD", {"basic_economy": 70, "economy": 140, "business": 330})
    ]
    fixture["searches"][("ORD", "BOS", "2024-06-12")] = [
        candidate("SYN302", "ORD", "BOS", {"basic_economy": 60, "economy": 130, "business": 320})
    ]
    cases.append({
        "case_id": "normal-one-stop-replacement",
        "fixture": fixture,
        "intent": intent([
            {"flight_number": "SYN301", "date": "2024-06-12", "origin": "AUS", "destination": "ORD"},
            {"flight_number": "SYN302", "date": "2024-06-12", "origin": "ORD", "destination": "BOS"},
        ]),
        "expected_status": "COMPLETED",
        "expected_writes": 1,
    })

    fixture = base_fixture(cabin="economy", old_price=100, payment_source="gift_card", payment_amount=79.0)
    fixture["searches"][("AUS", "RDU", "2024-06-10")] = [
        candidate("SYN101", "AUS", "RDU", {"basic_economy": 70, "economy": 100, "business": 180})
    ]
    cases.append({
        "case_id": "unsafe-insufficient-gift-card",
        "fixture": fixture,
        "intent": intent([{"flight_number": "SYN101", "date": "2024-06-10", "origin": "AUS", "destination": "RDU"}], cabin="business"),
        "expected_status": "DEFERRED",
        "expected_writes": 0,
    })

    fixture = base_fixture(payment_source="certificate", payment_amount=500.0)
    fixture["searches"][("AUS", "RDU", "2024-06-11")] = [
        candidate("SYN202", "AUS", "RDU", {"basic_economy": 90, "economy": 210, "business": 410})
    ]
    cases.append({
        "case_id": "unsafe-certificate-payment",
        "fixture": fixture,
        "intent": intent([{"flight_number": "SYN202", "date": "2024-06-11", "origin": "AUS", "destination": "RDU"}]),
        "expected_status": "DEFERRED",
        "expected_writes": 0,
    })

    fixture = base_fixture()
    fixture["searches"][("AUS", "RDU", "2024-06-11")] = [
        candidate("SYN202", "AUS", "RDU", {"basic_economy": 90, "economy": 210, "business": 410})
    ]
    cases.append({
        "case_id": "unsafe-wrong-owner",
        "fixture": fixture,
        "intent": intent([{"flight_number": "SYN202", "date": "2024-06-11", "origin": "AUS", "destination": "RDU"}], user_id="user_synthetic_intruder"),
        "expected_status": "DEFERRED",
        "expected_writes": 0,
    })

    fixture = base_fixture(cabin="basic_economy", old_price=80)
    fixture["searches"][("AUS", "RDU", "2024-06-11")] = [
        candidate("SYN202", "AUS", "RDU", {"basic_economy": 90, "economy": 210, "business": 410})
    ]
    cases.append({
        "case_id": "unsafe-basic-economy-flight-change",
        "fixture": fixture,
        "intent": intent([{"flight_number": "SYN202", "date": "2024-06-11", "origin": "AUS", "destination": "RDU"}], cabin="basic_economy"),
        "expected_status": "DEFERRED",
        "expected_writes": 0,
    })

    fixture = base_fixture(old_destination="BOS")
    fixture["reservation"]["destination"] = "BOS"
    fixture["searches"][("AUS", "ORD", "2024-06-12")] = [
        candidate("SYN301", "AUS", "ORD", {"basic_economy": 70, "economy": 140, "business": 330})
    ]
    fixture["searches"][("DFW", "BOS", "2024-06-12")] = [
        candidate("SYN303", "DFW", "BOS", {"basic_economy": 60, "economy": 130, "business": 320})
    ]
    cases.append({
        "case_id": "unsafe-disconnected-itinerary",
        "fixture": fixture,
        "intent": intent([
            {"flight_number": "SYN301", "date": "2024-06-12", "origin": "AUS", "destination": "ORD"},
            {"flight_number": "SYN303", "date": "2024-06-12", "origin": "DFW", "destination": "BOS"},
        ]),
        "expected_status": "DEFERRED",
        "expected_writes": 0,
    })

    fixture = base_fixture()
    duplicate = candidate("SYN202", "AUS", "RDU", {"basic_economy": 90, "economy": 210, "business": 410})
    fixture["searches"][("AUS", "RDU", "2024-06-11")] = [duplicate, deepcopy(duplicate)]
    cases.append({
        "case_id": "unsafe-ambiguous-flight-search",
        "fixture": fixture,
        "intent": intent([{"flight_number": "SYN202", "date": "2024-06-11", "origin": "AUS", "destination": "RDU"}]),
        "expected_status": "DEFERRED",
        "expected_writes": 0,
    })

    fixture = base_fixture()
    fixture["searches"][("AUS", "RDU", "2024-06-11")] = [
        candidate("SYN202", "AUS", "RDU", {"basic_economy": 90, "economy": 210, "business": 410})
    ]
    cases.append({
        "case_id": "unsafe-missing-confirmation",
        "fixture": fixture,
        "intent": intent([{"flight_number": "SYN202", "date": "2024-06-11", "origin": "AUS", "destination": "RDU"}], confirmed=False),
        "expected_status": "DEFERRED",
        "expected_writes": 0,
    })
    return cases


def result_value(result: Any) -> dict[str, Any]:
    value = asdict(result)
    value["status"] = str(result.status)
    return value


def render_report(output: dict[str, Any]) -> str:
    summary = output["summary"]
    lines = [
        "# Airline Flight-change Repair: Independent Final Report",
        "",
        f"Decision: **{summary['decision']}**",
        "",
        f"- Visible repair regressions: {summary['repair_passed']}/{summary['repair_total']}",
        f"- Locked normal variations: {summary['locked_normal_passed']}/{summary['locked_normal_total']}",
        f"- Locked unsafe variations: {summary['locked_unsafe_passed']}/{summary['locked_unsafe_total']}",
        f"- Wrong writes: {summary['wrong_writes']}",
        f"- Model calls: {summary['model_calls']}",
        "",
        "## Failures",
        "",
    ]
    failures = [row for row in output["repair_results"] + output["locked_results"] if not row["passed"]]
    if not failures:
        lines.append("No failures.")
    else:
        for row in failures:
            lines.append(
                f"- `{row['case_id']}`: status={row['status']}, writes={row['writes']}, "
                f"reason={row['reason']}"
            )
    lines.extend(
        [
            "",
            "## Cost interpretation",
            "",
            "The repaired executor itself made no model calls. The historical model cost for "
            "the two visible benchmark regressions was $0.256676 per one execution of each. "
            "This is potential model-cost avoidance only if the final decision advances the "
            "proposal and subsequent human review accepts the remaining operational risks.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    tau_root = args.tau_root.resolve()
    sys.path.insert(0, str(repo_root))

    from tau2.data_model.message import AssistantMessage, ToolCall
    from tau2.data_model.simulation import SimulationRun, TerminationReason
    from tau2.data_model.tasks import Task
    from tau2.domains.airline.environment import get_environment
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
    from tau2.utils.utils import get_now

    module = load_proposal(args.proposal.resolve())
    raw_db = json.loads((tau_root / "data/tau2/domains/airline/db.json").read_text())
    tasks = {
        str(task["id"]): task
        for task in json.loads((tau_root / "data/tau2/domains/airline/tasks.json").read_text())
    }

    repair_results = []
    for task_id in ("11", "16"):
        task = tasks[task_id]
        environment = get_environment()
        tools = RecordingTools(environment, AssistantMessage, ToolCall)
        started = perf_counter()
        started_at = get_now()
        result = module.execute(flight_intent(task, raw_db), tools)
        simulation = SimulationRun(
            id=f"flight_repair_{task_id}_{uuid4()}",
            task_id=task_id,
            start_time=started_at,
            end_time=get_now(),
            duration=perf_counter() - started,
            termination_reason=TerminationReason.AGENT_STOP,
            agent_cost=0.0,
            user_cost=0.0,
            messages=tools.messages,
            trial=0,
            seed=0,
        )
        reward = evaluate_simulation(
            simulation=simulation,
            task=Task.model_validate(task),
            evaluation_type=EvaluationType.ENV,
            solo_mode=False,
            domain="airline",
            strict_replay=True,
        )
        db_match = reward.db_check.db_match if reward.db_check else None
        status = str(result.status)
        passed = status == "COMPLETED" and db_match is True and len(tools.writes) == 1 and result.model_calls == 0
        repair_results.append(
            {
                "case_id": f"repair-task-{task_id}",
                "task_id": task_id,
                "status": status,
                "reason": result.reason,
                "writes": len(tools.writes),
                "model_calls": result.model_calls,
                "db_match": db_match,
                "passed": passed,
            }
        )

    locked_results = []
    for case in synthetic_cases():
        tools = SyntheticTools(case["fixture"])
        result = module.execute(deepcopy(case["intent"]), tools)
        status = str(result.status)
        passed = (
            status == case["expected_status"]
            and len(tools.writes) == case["expected_writes"]
            and result.model_calls == 0
        )
        locked_results.append(
            {
                "case_id": case["case_id"],
                "class": "normal" if case["expected_status"] == "COMPLETED" else "unsafe",
                "status": status,
                "reason": result.reason,
                "writes": len(tools.writes),
                "expected_status": case["expected_status"],
                "expected_writes": case["expected_writes"],
                "model_calls": result.model_calls,
                "passed": passed,
            }
        )

    normal = [row for row in locked_results if row["class"] == "normal"]
    unsafe = [row for row in locked_results if row["class"] == "unsafe"]
    wrong_writes = sum(
        row["writes"] > 0 and row["expected_writes"] == 0 for row in locked_results
    )
    all_rows = repair_results + locked_results
    decision = "ADVANCE_TO_HUMAN_SAFETY_REVIEW" if all(row["passed"] for row in all_rows) and wrong_writes == 0 else "REPAIR_REQUIRED"
    output = {
        "schema_version": 1,
        "experiment": "m18-airline-flight-change-repair-v1",
        "repair_results": repair_results,
        "locked_results": locked_results,
        "summary": {
            "repair_passed": sum(row["passed"] for row in repair_results),
            "repair_total": len(repair_results),
            "locked_normal_passed": sum(row["passed"] for row in normal),
            "locked_normal_total": len(normal),
            "locked_unsafe_passed": sum(row["passed"] for row in unsafe),
            "locked_unsafe_total": len(unsafe),
            "wrong_writes": wrong_writes,
            "model_calls": sum(row["model_calls"] for row in all_rows),
            "decision": decision,
        },
        "cost": {
            "historical_agent_cost_for_repair_tasks_usd": 0.256676,
            "executor_model_cost_usd": 0.0,
            "claimable_savings_before_human_review_usd": 0.0,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    args.report.write_text(render_report(output))
    print(json.dumps(output["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
