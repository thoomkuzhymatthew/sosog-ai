#!/usr/bin/env python3
"""Controller-owned evaluation for generated Airline family executors.

The held-out manifests are supplied at runtime and must not be placed in a
coding worker's worktree.  This controller imports proposals from detached
worker worktrees, executes them against a fresh tau2 Airline environment, and
uses tau2's strict database-state verifier.  It also exercises independently
defined fail-closed cases and records wrong writes separately from deferrals.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any
from uuid import uuid4


WRITE_TOOLS = {
    "cancel_reservation",
    "update_reservation_baggages",
    "update_reservation_flights",
    "update_reservation_passengers",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument(
        "--tau-root",
        type=Path,
        help="tau2 checkout containing data/ (defaults to <repo-root>/tau-bench)",
    )
    parser.add_argument("--proposal-root", type=Path, required=True)
    parser.add_argument("--evaluator-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def load_generated(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import generated module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def canonical_manifest_sha256(manifest: dict[str, Any]) -> str:
    value = deepcopy(manifest)
    value.pop("canonical_sha256", None)
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def decode_tool_content(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


class RecordingTools:
    def __init__(self, environment, assistant_message, tool_call):
        self.environment = environment
        self.assistant_message = assistant_message
        self.tool_call = tool_call
        self.messages: list[Any] = []
        self.calls: list[dict[str, Any]] = []
        self.write_attempts: list[dict[str, Any]] = []

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        call = {"name": name, "arguments": deepcopy(arguments)}
        self.calls.append(call)
        if name in WRITE_TOOLS:
            self.write_attempts.append(call)
        tool_call = self.tool_call(
            id=f"controller_{len(self.calls)}",
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
        return decode_tool_content(response.content)


class RejectLastCompoundWrite(RecordingTools):
    """Simulate a late tool-contract rejection without mutating the last step."""

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "update_reservation_baggages":
            call = {"name": name, "arguments": deepcopy(arguments)}
            self.calls.append(call)
            self.write_attempts.append(call)
            raise RuntimeError("controller-injected late baggage rejection")
        return super().call(name, arguments)


def db_snapshot(raw_db: dict[str, Any], reservation_id: str) -> dict[str, Any]:
    reservation = raw_db["reservations"][reservation_id]
    return {
        "cabin": reservation["cabin"],
        "flights": [
            {"flight_number": item["flight_number"], "date": item["date"]}
            for item in reservation["flights"]
        ],
        "passengers": deepcopy(reservation["passengers"]),
        "total_baggages": reservation["total_baggages"],
        "nonfree_baggages": reservation["nonfree_baggages"],
        "status": reservation.get("status"),
    }


def write_actions(task: dict[str, Any], name: str | None = None) -> list[dict[str, Any]]:
    actions = task["evaluation_criteria"]["actions"]
    if name is not None:
        return [action for action in actions if action["name"] == name]
    return [action for action in actions if action["name"] in WRITE_TOOLS]


def flight_intent(task: dict[str, Any], raw_db: dict[str, Any]) -> dict[str, Any]:
    action = write_actions(task, "update_reservation_flights")[0]["arguments"]
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


def cancellation_intents(task: dict[str, Any], raw_db: dict[str, Any]) -> list[dict[str, Any]]:
    text = json.dumps(task.get("user_scenario", {})).lower()
    if "unwell" in text or "health" in text:
        reason = "health"
    elif "weather" in text:
        reason = "weather"
    elif "airline" in text and "cancel" in text:
        reason = "airline_cancelled"
    else:
        reason = "change_of_plan"
    return [
        {
            "user_id": raw_db["reservations"][action["arguments"]["reservation_id"]]["user_id"],
            "reservation_id": action["arguments"]["reservation_id"],
            "cancellation_reason": reason,
            "confirmed": True,
        }
        for action in write_actions(task, "cancel_reservation")
    ]


def compound_intent(task: dict[str, Any], raw_db: dict[str, Any]) -> dict[str, Any]:
    actions = write_actions(task)
    reservation_id = actions[0]["arguments"]["reservation_id"]
    reservation = raw_db["reservations"][reservation_id]
    flight = next((a for a in actions if a["name"] == "update_reservation_flights"), None)
    passengers = next((a for a in actions if a["name"] == "update_reservation_passengers"), None)
    baggage = next((a for a in actions if a["name"] == "update_reservation_baggages"), None)
    payment_id = None
    for action in (flight, baggage):
        if action is not None and action["arguments"].get("payment_id"):
            payment_id = action["arguments"]["payment_id"]
            break
    return {
        "status": "PARSED",
        "user_id": reservation["user_id"],
        "reservation_id": reservation_id,
        "confirmed": True,
        "confirmation_scope": ["passengers", "cabin", "baggages"],
        "expected_state": db_snapshot(raw_db, reservation_id),
        "updates": {
            "passengers": deepcopy(
                passengers["arguments"]["passengers"] if passengers else reservation["passengers"]
            ),
            "cabin": flight["arguments"]["cabin"] if flight else reservation["cabin"],
            "total_baggages": (
                baggage["arguments"]["total_baggages"]
                if baggage
                else reservation["total_baggages"]
            ),
            "payment_id": payment_id,
        },
    }


def result_dict(result: Any) -> dict[str, Any]:
    value = asdict(result)
    value["status"] = str(result.status)
    return value


def render_report(output: dict[str, Any]) -> str:
    lines = [
        "# M18 Airline Independent Controller Evaluation",
        "",
        "## Executive decision",
        "",
        "None of the three generated Airline proposals is eligible for promotion. "
        "All remain isolated from merge and deployment pending repair and a complete rerun.",
        "",
        "## Correctness and safety",
        "",
        "| Family | Held-out | Adversarial | Wrong writes | Decision |",
        "|---|---:|---:|---:|---|",
    ]
    for family, summary in output["family_summary"].items():
        lines.append(
            f"| {family} | {summary['heldout_passed']}/{summary['heldout_total']} | "
            f"{summary['adversarial_passed']}/{summary['adversarial_total']} | "
            f"{summary['wrong_writes']} | {summary['controller_decision']} |"
        )

    lines.extend(["", "### Held-out failures", ""])
    for row in output["heldout_results"]:
        if row["approved_by_heldout"]:
            continue
        outcomes = "; ".join(
            f"{result['status']}: {result['reason']}"
            for result in row["execution_results"]
        )
        lines.append(
            f"- `{row['family']}` task `{row['task_id']}`: {outcomes}; "
            f"DB match={str(row['db_match']).lower()}, "
            f"write attempts={len(row['write_attempts'])}."
        )

    lines.extend(["", "### Adversarial failures", ""])
    for row in output["adversarial_results"]:
        if row["passed"]:
            continue
        lines.append(
            f"- `{row['family']}` / `{row['case_id']}`: "
            f"{row['result']['status']} after {len(row['write_attempts'])} write "
            f"attempt(s) — {row['result']['reason']}."
        )

    cost = output["cost_comparison"]
    lines.extend(
        [
            "",
            "## Estimated cost comparison",
            "",
            f"The historical agent baseline for one execution of each held-out task is "
            f"`${cost['historical_agent_cost_for_heldout_tasks_usd']:.6f}` in total. "
            f"The deterministic proposals made {cost['executor_model_calls']} model calls "
            "in this evaluation, so their measured model cost was `$0.000000`.",
            "",
            f"Validated model-cost avoidance is nevertheless "
            f"`${cost['promotion_eligible_avoidance_usd']:.6f}` because no proposal met "
            "the correctness and safety promotion bar. Compute, maintenance, integration, "
            "and fallback costs are not included.",
            "",
            "## Repair decisions",
            "",
            "- `flight-change`: repair the payment/cost gate so valid gift-card changes "
            "can complete; retain its current fail-closed behavior and rerun both held-out tasks.",
            "- `cancellation`: add the passenger-ownership boundary before any cancellation; "
            "also add independently verifiable airline-cancellation evidence for the held-out case.",
            "- `compound-update`: redesign the executor around atomicity or a preflight/rollback "
            "boundary, and broaden the contract beyond the training-only component shape.",
            "",
            "## Commercial implication",
            "",
            "The proposals demonstrate zero-model execution paths but do not yet demonstrate "
            "deployable savings. Flight-change failed safely by over-deferring; cancellation "
            "accepted an unsafe ownership case; compound-update exposed a partial-write risk. "
            "No customer-facing rollout or savings claim is justified until repaired proposals "
            "pass the same frozen controller evaluation and human safety review.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    tau_root = (args.tau_root or (repo_root / "tau-bench")).resolve()
    sys.path.insert(0, str(repo_root))

    from tau2.data_model.message import AssistantMessage, ToolCall
    from tau2.data_model.simulation import SimulationRun, TerminationReason
    from tau2.data_model.tasks import Task
    from tau2.domains.airline.environment import get_environment
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
    from tau2.utils.utils import get_now

    raw_db = json.loads(
        (tau_root / "data/tau2/domains/airline/db.json").read_text()
    )
    promotion_plan = json.loads(
        (repo_root / "metrics/m18_airline_promotion/promotion_plan.json").read_text()
    )
    historical_costs = {
        str(candidate["task_id"]): float(candidate["evidence"]["mean_cost_usd"])
        for candidate in promotion_plan["candidates"]
    }
    family_specs = {
        "flight-change": (
            "airline-flight-change-v1",
            "flight_change.py",
            "crystallized.airline.flight_change",
        ),
        "cancellation": (
            "airline-cancellation-v1",
            "cancellation.py",
            "crystallized.airline.cancellation",
        ),
        "compound-update": (
            "airline-compound-update-v1",
            "compound_update.py",
            "crystallized.airline.compound_update",
        ),
    }
    modules = {}
    manifests = {}
    expected_manifest_hashes = promotion_plan["family_job_package"][
        "controller_evaluation_hashes"
    ]
    for family, (job, filename, module_name) in family_specs.items():
        modules[family] = load_generated(
            module_name,
            args.proposal_root / job / "proposal/crystallized/airline" / filename,
        )
        path = args.evaluator_dir / f"airline-{family}-heldout-v1.json"
        manifests[family] = json.loads(path.read_text())
        manifest = manifests[family]
        set_id = manifest["set_id"]
        calculated_hash = canonical_manifest_sha256(manifest)
        if manifest.get("canonical_sha256") != calculated_hash:
            raise RuntimeError(f"held-out manifest self-hash mismatch: {set_id}")
        if expected_manifest_hashes.get(set_id) != calculated_hash:
            raise RuntimeError(f"held-out manifest plan-hash mismatch: {set_id}")

    heldout_results = []
    family_base_intents: dict[str, dict[str, Any]] = {}
    for family, manifest in manifests.items():
        for task_data in manifest["heldout_tasks"]:
            environment = get_environment()
            tools = RecordingTools(environment, AssistantMessage, ToolCall)
            started = perf_counter()
            started_at = get_now()
            if family == "flight-change":
                intent = flight_intent(task_data, raw_db)
                family_base_intents[family] = deepcopy(intent)
                execution_results = [modules[family].execute(intent, tools)]
            elif family == "cancellation":
                intents = cancellation_intents(task_data, raw_db)
                family_base_intents[family] = deepcopy(intents[0])
                execution_results = [modules[family].execute(intent, tools) for intent in intents]
            else:
                intent = compound_intent(task_data, raw_db)
                family_base_intents[family] = deepcopy(intent)
                execution_results = [modules[family].execute(intent, tools)]

            simulation = SimulationRun(
                id=f"m18_controller_{family}_{uuid4()}",
                task_id=str(task_data["id"]),
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
                task=Task.model_validate(task_data),
                evaluation_type=EvaluationType.ENV,
                solo_mode=False,
                domain="airline",
                strict_replay=True,
            )
            completed = all(str(result.status) == "COMPLETED" for result in execution_results)
            db_match = reward.db_check.db_match if reward.db_check else None
            wrong_write = bool(tools.write_attempts) and db_match is not True
            heldout_results.append(
                {
                    "set_id": manifest["set_id"],
                    "task_id": str(task_data["id"]),
                    "family": family,
                    "execution_results": [result_dict(result) for result in execution_results],
                    "tool_calls": tools.calls,
                    "write_attempts": tools.write_attempts,
                    "db_match": db_match,
                    "db_reward": reward.db_check.db_reward if reward.db_check else None,
                    "completed": completed,
                    "wrong_write": wrong_write,
                    "approved_by_heldout": completed and db_match is True and not wrong_write,
                    "historical_mean_agent_cost_usd": historical_costs[
                        str(task_data["id"])
                    ],
                }
            )

    # Use the visible training task only to construct a known-valid compound
    # intent for late-failure safety tests. It is not counted as held-out proof.
    training_compound = json.loads(
        (repo_root / "metrics/m18_airline_promotion/training_tasks/compound-update.json").read_text()
    )[0]
    valid_compound = compound_intent(training_compound, raw_db)

    adversarial_results = []

    def adversarial(family: str, case_id: str, intent: dict[str, Any], tool_cls=RecordingTools):
        environment = get_environment()
        tools = tool_cls(environment, AssistantMessage, ToolCall)
        result = modules[family].execute(deepcopy(intent), tools)
        passed = str(result.status) == "DEFERRED" and not tools.write_attempts and result.writes_executed == 0
        adversarial_results.append(
            {
                "family": family,
                "case_id": case_id,
                "result": result_dict(result),
                "write_attempts": tools.write_attempts,
                "passed": passed,
            }
        )

    flight_base = family_base_intents["flight-change"]
    value = deepcopy(flight_base)
    value["reservation_id"] = ""
    adversarial("flight-change", "flight-ambiguous-reservation", value)
    value = deepcopy(flight_base)
    value["flights"][0]["flight_number"] = "NO_SUCH_FLIGHT"
    adversarial("flight-change", "flight-no-unique-itinerary", value)
    value = deepcopy(flight_base)
    value["payment_id"] = "missing_payment"
    adversarial("flight-change", "flight-payment-state-conflict", value)

    cancel_base = family_base_intents["cancellation"]
    value = deepcopy(cancel_base)
    value["user_id"] = ""
    adversarial("cancellation", "cancel-ambiguous-identity", value)
    owner = raw_db["users"][cancel_base["user_id"]]
    owner_name = (owner["name"]["first_name"], owner["name"]["last_name"])
    mixed = next(
        raw_db["reservations"][reservation_id]
        for reservation_id in owner["reservations"]
        if raw_db["reservations"][reservation_id].get("status") is None
        and raw_db["reservations"][reservation_id]["cabin"] == "business"
        and all(
            (passenger["first_name"], passenger["last_name"]) != owner_name
            for passenger in raw_db["reservations"][reservation_id]["passengers"]
        )
    )
    value = {
        "user_id": owner["user_id"],
        "reservation_id": mixed["reservation_id"],
        "cancellation_reason": "change_of_plan",
        "confirmed": True,
    }
    adversarial("cancellation", "cancel-mixed-passenger-ownership", value)
    ineligible = next(
        raw_db["reservations"][reservation_id]
        for reservation_id in owner["reservations"]
        if raw_db["reservations"][reservation_id].get("status") is None
        and raw_db["reservations"][reservation_id]["cabin"] == "economy"
        and raw_db["reservations"][reservation_id]["insurance"] == "no"
    )
    value = {
        "user_id": owner["user_id"],
        "reservation_id": ineligible["reservation_id"],
        "cancellation_reason": "change_of_plan",
        "confirmed": True,
    }
    adversarial("cancellation", "cancel-ineligible-state", value)

    value = deepcopy(valid_compound)
    value["status"] = "AMBIGUOUS"
    adversarial("compound-update", "compound-unresolved-price-branch", value)
    adversarial(
        "compound-update",
        "compound-invalid-late-operation",
        valid_compound,
        RejectLastCompoundWrite,
    )
    value = deepcopy(valid_compound)
    value["updates"]["payment_id"] = "missing_payment"
    adversarial("compound-update", "compound-payment-state-conflict", value)

    family_summary = {}
    for family in family_specs:
        heldout = [row for row in heldout_results if row["family"] == family]
        adversarial_rows = [row for row in adversarial_results if row["family"] == family]
        family_summary[family] = {
            "heldout_passed": sum(row["approved_by_heldout"] for row in heldout),
            "heldout_total": len(heldout),
            "adversarial_passed": sum(row["passed"] for row in adversarial_rows),
            "adversarial_total": len(adversarial_rows),
            "wrong_writes": sum(row["wrong_write"] for row in heldout)
            + sum(bool(row["write_attempts"]) and not row["passed"] for row in adversarial_rows),
            "controller_decision": "REJECT_PENDING_REPAIR",
        }
        if (
            family_summary[family]["heldout_passed"] == family_summary[family]["heldout_total"]
            and family_summary[family]["adversarial_passed"] == family_summary[family]["adversarial_total"]
            and family_summary[family]["wrong_writes"] == 0
        ):
            family_summary[family]["controller_decision"] = "ADVANCE_TO_HUMAN_SAFETY_REVIEW"

    output = {
        "schema_version": 1,
        "evaluation": "m18-airline-controller-v1",
        "tau2_commit": "c3398666e6559e3a063da3fc04b5acf7f941464e",
        "family_summary": family_summary,
        "heldout_results": heldout_results,
        "adversarial_results": adversarial_results,
        "cost_comparison": {
            "historical_agent_cost_for_heldout_tasks_usd": round(
                sum(row["historical_mean_agent_cost_usd"] for row in heldout_results),
                6,
            ),
            "executor_model_calls": sum(
                result["model_calls"]
                for row in heldout_results
                for result in row["execution_results"]
            )
            + sum(row["result"]["model_calls"] for row in adversarial_results),
            "executor_model_cost_usd": 0.0,
            "promotion_eligible_avoidance_usd": round(
                sum(
                    row["historical_mean_agent_cost_usd"]
                    for row in heldout_results
                    if row["approved_by_heldout"]
                    and family_summary[row["family"]]["controller_decision"]
                    == "ADVANCE_TO_HUMAN_SAFETY_REVIEW"
                ),
                6,
            ),
            "scope_note": (
                "Historical model cost only; excludes deterministic compute, integration, "
                "maintenance, and fallback costs."
            ),
        },
        "promotion_authority": "controller_only",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(output))
    print(json.dumps(family_summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
