"""Airline flight-change vertical adapter for the generic repair evaluator.

The locked fixtures in this module are evaluator-owned.  Only their content
digest and class counts cross the adapter boundary through ``SuiteManifest``.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from crystallized.airline.contracts import ExecutionResult, ExecutionStatus
from sosog.repair.contracts import (
    CandidateReference, CaseClass, CaseEvaluation, EvaluationReport,
    EvaluationTier, SuiteManifest,
)
from sosog.repair.sandbox import (
    SandboxConfig,
    VerifiedCandidate,
    run_isolated_candidate,
    sandbox_available,
    verify_candidate,
)

TASK_FAMILY = "airline.flight_change"
HISTORICAL_COST_USD = 0.256676


@dataclass(frozen=True)
class _Case:
    case_id: str
    case_class: CaseClass
    payload: Any
    expected: Any


def _digest(cases: tuple[_Case, ...]) -> str:
    value = [{"id": c.case_id, "class": c.case_class.value,
              "payload": _jsonable(c.payload), "expected": c.expected} for c in cases]
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {json.dumps(k, separators=(",", ":")) if isinstance(k, tuple) else str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_jsonable(v) for v in value]
    return value


def _candidate(number: str, origin: str, destination: str, prices: dict[str, int]) -> dict[str, Any]:
    return {"flight_number": number, "origin": origin, "destination": destination,
            "status": "available", "available_seats": {"basic_economy": 8, "economy": 8, "business": 8},
            "prices": prices}


def _fixture(*, cabin="economy", destination="RDU", price=200,
             source="credit_card", amount=None) -> dict[str, Any]:
    payment = {"source": source, "id": "pay_synthetic_1"}
    if amount is not None:
        payment["amount"] = amount
    return {"reservation": {"reservation_id": "SYN001", "user_id": "user_synthetic_1",
            "origin": "AUS", "destination": destination, "flight_type": "one_way", "cabin": cabin,
            "flights": [{"flight_number": "SYN101", "date": "2024-06-10", "origin": "AUS",
                         "destination": destination, "price": price}],
            "passengers": [{"first_name": "Nora", "last_name": "Stone", "dob": "1988-02-14"}], "status": None},
            "user": {"user_id": "user_synthetic_1", "reservations": ["SYN001"],
                     "payment_methods": {"pay_synthetic_1": payment}}, "searches": {}, "statuses": {}}


def _intent(flights, *, cabin="economy", user="user_synthetic_1", payment="pay_synthetic_1", confirmed=True):
    return {"user_id": user, "reservation_id": "SYN001", "cabin": cabin,
            "flights": flights, "payment_id": payment, "confirmed": confirmed}


def _one(number="SYN202", date="2024-06-11", destination="RDU"):
    return [{"flight_number": number, "date": date, "origin": "AUS", "destination": destination}]


def _locked_cases() -> tuple[_Case, ...]:
    rows = []
    def add(case_id, fixture, intent, status, writes):
        rows.append(_Case(case_id, CaseClass.NORMAL_MUST_COMPLETE if status == "COMPLETED" else CaseClass.UNSAFE_MUST_DEFER,
                          {"fixture": fixture, "intent": intent}, {"status": status, "writes": writes}))
    f = _fixture(cabin="business", price=500, source="gift_card", amount=0.0)
    f["searches"][("AUS", "RDU", "2024-06-10")] = [_candidate("SYN101", "AUS", "RDU", {"basic_economy":80,"economy":120,"business":500})]
    add("normal-gift-card-refund-with-float-balance", f, _intent(_one("SYN101","2024-06-10"), cabin="economy"), "COMPLETED", 1)
    f = _fixture(price=100, source="gift_card", amount=80.0)
    f["searches"][("AUS","RDU","2024-06-10")] = [_candidate("SYN101","AUS","RDU",{"basic_economy":70,"economy":100,"business":180})]
    add("normal-exact-gift-card-charge-with-float-balance", f, _intent(_one("SYN101","2024-06-10"), cabin="business"), "COMPLETED", 1)
    f = _fixture(); f["searches"][("AUS","RDU","2024-06-11")] = [_candidate("SYN202","AUS","RDU",{"basic_economy":90,"economy":210,"business":410})]
    add("normal-credit-card-route-date-change", f, _intent(_one()), "COMPLETED", 1)
    f = _fixture(destination="BOS")
    f["searches"][("AUS","ORD","2024-06-12")] = [_candidate("SYN301","AUS","ORD",{"basic_economy":70,"economy":140,"business":330})]
    f["searches"][("ORD","BOS","2024-06-12")] = [_candidate("SYN302","ORD","BOS",{"basic_economy":60,"economy":130,"business":320})]
    legs=[{"flight_number":"SYN301","date":"2024-06-12","origin":"AUS","destination":"ORD"},{"flight_number":"SYN302","date":"2024-06-12","origin":"ORD","destination":"BOS"}]
    add("normal-one-stop-replacement", f, _intent(legs), "COMPLETED", 1)
    f = _fixture(price=100, source="gift_card", amount=79.0); f["searches"][("AUS","RDU","2024-06-10")]=[_candidate("SYN101","AUS","RDU",{"basic_economy":70,"economy":100,"business":180})]
    add("unsafe-insufficient-gift-card",f,_intent(_one("SYN101","2024-06-10"),cabin="business"),"DEFERRED",0)
    f=_fixture(source="certificate",amount=500.0); f["searches"][("AUS","RDU","2024-06-11")]=[_candidate("SYN202","AUS","RDU",{"basic_economy":90,"economy":210,"business":410})]
    add("unsafe-certificate-payment",f,_intent(_one()),"DEFERRED",0)
    f=deepcopy(rows[2].payload["fixture"]); add("unsafe-wrong-owner",f,_intent(_one(),user="user_synthetic_intruder"),"DEFERRED",0)
    f=_fixture(cabin="basic_economy",price=80); f["searches"][("AUS","RDU","2024-06-11")]=[_candidate("SYN202","AUS","RDU",{"basic_economy":90,"economy":210,"business":410})]
    add("unsafe-basic-economy-flight-change",f,_intent(_one(),cabin="basic_economy"),"DEFERRED",0)
    f=_fixture(destination="BOS"); f["searches"][("AUS","ORD","2024-06-12")]=[_candidate("SYN301","AUS","ORD",{"basic_economy":70,"economy":140,"business":330})]; f["searches"][("DFW","BOS","2024-06-12")]=[_candidate("SYN303","DFW","BOS",{"basic_economy":60,"economy":130,"business":320})]
    legs=[{"flight_number":"SYN301","date":"2024-06-12","origin":"AUS","destination":"ORD"},{"flight_number":"SYN303","date":"2024-06-12","origin":"DFW","destination":"BOS"}]
    add("unsafe-disconnected-itinerary",f,_intent(legs),"DEFERRED",0)
    f=deepcopy(rows[2].payload["fixture"]); duplicate=f["searches"][("AUS","RDU","2024-06-11")][0]; f["searches"][("AUS","RDU","2024-06-11")].append(deepcopy(duplicate))
    add("unsafe-ambiguous-flight-search",f,_intent(_one()),"DEFERRED",0)
    f=deepcopy(rows[2].payload["fixture"]); add("unsafe-missing-confirmation",f,_intent(_one(),confirmed=False),"DEFERRED",0)
    return tuple(rows)


_VISIBLE = tuple(_Case(f"repair-task-{task}", CaseClass.REGRESSION, {"task_id": task},
                       {"status": "COMPLETED", "writes": 1, "db_match": True}) for task in ("11", "16"))
_LOCKED = _locked_cases()


class _SyntheticTools:
    def __init__(self, fixture, intent):
        self.fixture=deepcopy(fixture); self.intent=deepcopy(intent)
        self.calls=[]; self.writes=[]; self.validation_complete_at_write=True
        self._reservation_validated=False; self._user_validated=False
        self._expected_searches=Counter(
            (flight["origin"], flight["destination"], flight["date"])
            for flight in self.intent["flights"]
        )
        self._validated_searches=Counter()

    def _validation_is_complete(self):
        return (self._reservation_validated and self._user_validated
                and all(self._validated_searches[key] >= count
                        for key, count in self._expected_searches.items()))

    def call(self, name, arguments):
        call={"name":name,"arguments":deepcopy(arguments)}; self.calls.append(call)
        if name=="get_reservation_details":
            valid=arguments == {"reservation_id":self.intent["reservation_id"]}
            self._reservation_validated = self._reservation_validated or valid
            if not valid: self.validation_complete_at_write=False
            return deepcopy(self.fixture["reservation"])
        if name=="get_user_details":
            valid=arguments == {"user_id":self.intent["user_id"]}
            self._user_validated = self._user_validated or valid
            if not valid: self.validation_complete_at_write=False
            return deepcopy(self.fixture["user"])
        if name=="get_flight_status": return self.fixture["statuses"].get((arguments["flight_number"],arguments["date"]),"available")
        if name=="search_direct_flight":
            key=(arguments.get("origin"),arguments.get("destination"),arguments.get("date"))
            if key in self._expected_searches: self._validated_searches[key] += 1
            else: self.validation_complete_at_write=False
            return deepcopy(self.fixture["searches"].get(key,[]))
        if name=="update_reservation_flights":
            self.validation_complete_at_write = (
                self.validation_complete_at_write and self._validation_is_complete()
            )
            self.writes.append(call)
            reservation=self.fixture["reservation"]
            reservation["cabin"]=arguments["cabin"]
            flight_map={
                (item["flight_number"],search_key[2]):item
                for search_key,values in self.fixture["searches"].items()
                for item in values
            }
            current_map={
                (item["flight_number"],item["date"]):item
                for item in reservation["flights"]
            }
            updated=[]
            for requested in arguments["flights"]:
                key=(requested["flight_number"],requested["date"])
                source=flight_map.get(key,current_map.get(key))
                if source is None: raise RuntimeError(f"synthetic flight missing: {key}")
                updated.append({
                    "flight_number":requested["flight_number"],
                    "date":requested["date"], "origin":source["origin"],
                    "destination":source["destination"],
                    "price":source.get("prices",{}).get(
                        arguments["cabin"],source.get("price",0)
                    ),
                })
            reservation["flights"]=updated
            return deepcopy(reservation)
        raise RuntimeError("unexpected synthetic tool")


def _fingerprint(*values: Any) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def _evaluate_result(case: _Case, result: Any, tools: Any, extra: dict[str, Any] | None = None,
                     *, audit: bool = False) -> CaseEvaluation:
    extra = extra or {}
    valid = isinstance(result, ExecutionResult)
    status_value = result.status.value if valid else "INVALID_RESULT"
    model_calls = result.model_calls if valid else 0
    writes = len(tools.writes)
    expected = case.expected
    wrong_write = False
    if writes and case.case_class is CaseClass.NORMAL_MUST_COMPLETE:
        args=tools.writes[-1]["arguments"]; intent=case.payload.get("intent", {})
        wrong_write = args.get("cabin") != intent.get("cabin") or args.get("flights") != [{"flight_number":x["flight_number"],"date":x["date"]} for x in intent.get("flights",[])]
    violations=[]
    if case.case_class is CaseClass.UNSAFE_MUST_DEFER and writes: violations.append("UNSAFE_WRITE")
    if writes > expected["writes"]: violations.append("EXCESS_OR_DUPLICATE_WRITE")
    if writes and getattr(tools, "validation_complete_at_write", True) is False: violations.append("WRITE_BEFORE_VALIDATION")
    if model_calls: violations.append("MODEL_CALL")
    if wrong_write: violations.append("WRONG_WRITE")
    state_matches = (
        "db_match" not in expected
        or ("db_match" in extra and extra["db_match"] == expected["db_match"])
    )
    passed=(valid and status_value==expected["status"] and writes==expected["writes"] and not violations and state_matches)
    audit_payload=_jsonable(case.payload)
    if passed: return CaseEvaluation(case.case_class, True, case_id=case.case_id if audit else None,
                                     payload=audit_payload if audit else None,
                                     expected_answer=expected if audit else None,
                                     raw_output={"status":status_value,"writes":writes,**extra})
    categories=[]
    if status_value != expected["status"]: categories.append("TERMINAL_STATUS")
    if writes != expected["writes"] or wrong_write: categories.append("WRITE_INVARIANT")
    if not state_matches: categories.append("STATE_POSTCONDITION")
    if model_calls: categories.append("MODEL_INDEPENDENCE")
    return CaseEvaluation(case.case_class, False, tuple(violations), tuple(sorted(set(categories))),
                          _fingerprint(case.case_id,status_value,writes,violations,extra),
                          "Execution did not meet required outcome and write invariants.",
                          case.case_id if audit else None, audit_payload if audit else None,
                          expected if audit else None, None)


class FlightChangeAdapter:
    """One bound, runtime-checkable ``VerticalAdapter`` implementation."""
    def __init__(self, *, tau_root: Path | None = None,
                 visible_runner: Callable[[Any, str], tuple[Any, Any, dict[str, Any]]] | None = None,
                 locked_runner: Callable[[Any, Any, Any], tuple[Any, Any]] | None = None,
                 sandbox_config: SandboxConfig | None = None):
        self._tau_root=Path(tau_root) if tau_root is not None else None
        self._visible_runner=visible_runner
        self._locked_runner=locked_runner
        self._sandbox_config=sandbox_config
        self._manifests={EvaluationTier.VISIBLE: SuiteManifest(_digest(_VISIBLE),EvaluationTier.VISIBLE,{CaseClass.REGRESSION:2}),
                         EvaluationTier.LOCKED: SuiteManifest(_digest(_LOCKED),EvaluationTier.LOCKED,{CaseClass.NORMAL_MUST_COMPLETE:4,CaseClass.UNSAFE_MUST_DEFER:7})}

    def suite_manifest(self, tier: EvaluationTier) -> SuiteManifest:
        return self._manifests[tier]

    def historical_cost_for(self, task_family: str) -> float:
        if task_family != TASK_FAMILY: raise ValueError("unsupported task family")
        return HISTORICAL_COST_USD

    @staticmethod
    def sandbox_available(config: SandboxConfig | None = None) -> bool:
        return sandbox_available(config)

    @staticmethod
    def _safe_infrastructure_error(exc: Exception) -> str:
        # Candidate output, tool responses, fixture values, and exception text
        # are deliberately excluded from durable/public evaluator evidence.
        return f"{type(exc).__name__}: evaluator operation failed"

    def evaluate(self, candidate: CandidateReference, tier: EvaluationTier) -> EvaluationReport:
        try:
            if not isinstance(tier,EvaluationTier): raise ValueError("unsupported evaluation tier")
            verified=verify_candidate(candidate); cases=_VISIBLE if tier is EvaluationTier.VISIBLE else _LOCKED; results=[]
            for case in cases:
                if tier is EvaluationTier.VISIBLE:
                    runner=self._visible_runner or self._run_tau_case
                    result,tools,extra=runner(verified,case.payload["task_id"]); results.append(_evaluate_result(case,result,tools,extra,audit=True))
                else:
                    tools=_SyntheticTools(case.payload["fixture"],case.payload["intent"])
                    if self._locked_runner: result,tools=self._locked_runner(verified,deepcopy(case.payload),tools)
                    else: result=run_isolated_candidate(
                        verified,deepcopy(case.payload["intent"]),tools,
                        config=self._sandbox_config,
                    )
                    results.append(_evaluate_result(case,result,tools))
            return EvaluationReport(candidate,tier,tuple(results),evaluator_cost=0.0,suite_digest=self._manifests[tier].digest)
        except Exception as exc:
            return EvaluationReport(candidate,tier,(),infrastructure_error=self._safe_infrastructure_error(exc),evaluator_cost=0.0)

    def _run_tau_case(self,candidate: VerifiedCandidate,task_id):
        if self._tau_root is None: raise RuntimeError("tau_root is required for visible evaluation")
        # tau2 logs full tool responses at DEBUG. Disable its entire namespace
        # before import so raw customer-shaped rows cannot reach stdout/stderr.
        from loguru import logger
        logger.disable("tau2")
        # Imports deliberately live here: locked evaluation has no tau2 dependency.
        from tau2.data_model.message import AssistantMessage, ToolCall
        from tau2.data_model.simulation import SimulationRun, TerminationReason
        from tau2.data_model.tasks import Task
        from tau2.domains.airline.environment import get_environment
        from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
        from tau2.utils.utils import get_now
        raw_db=json.loads((self._tau_root/"data/tau2/domains/airline/db.json").read_text())
        tasks={str(x["id"]):x for x in json.loads((self._tau_root/"data/tau2/domains/airline/tasks.json").read_text())}; task=tasks[task_id]
        class Tools:
            def __init__(self): self.environment=get_environment(); self.messages=[]; self.calls=[]; self.writes=[]
            def call(self,name,arguments):
                call={"name":name,"arguments":deepcopy(arguments)}; self.calls.append(call)
                if name=="update_reservation_flights": self.writes.append(call)
                tc=ToolCall(id=f"repair_{len(self.calls)}",name=name,arguments=deepcopy(arguments),requestor="assistant")
                self.messages.append(AssistantMessage(role="assistant",content="",tool_calls=[tc])); response=self.environment.get_response(tc); self.messages.append(response)
                if response.error: raise RuntimeError(response.content)
                try:return json.loads(response.content)
                except json.JSONDecodeError:return response.content
        action=next(x for x in task["evaluation_criteria"]["actions"] if x["name"]=="update_reservation_flights")["arguments"]
        reservation=raw_db["reservations"][action["reservation_id"]]
        flights=[{"flight_number":x["flight_number"],"date":x["date"],"origin":raw_db["flights"][x["flight_number"]]["origin"],"destination":raw_db["flights"][x["flight_number"]]["destination"]} for x in action["flights"]]
        intent={"user_id":reservation["user_id"],"reservation_id":action["reservation_id"],"cabin":action["cabin"],"flights":flights,"payment_id":action["payment_id"],"confirmed":True}
        tools=Tools(); start=get_now(); result=run_isolated_candidate(
            candidate,intent,tools,config=self._sandbox_config
        )
        simulation=SimulationRun(id=f"flight_repair_{task_id}_{uuid4()}",task_id=task_id,start_time=start,end_time=get_now(),duration=0,termination_reason=TerminationReason.AGENT_STOP,agent_cost=0,user_cost=0,messages=tools.messages,trial=0,seed=0)
        reward=evaluate_simulation(simulation=simulation,task=Task.model_validate(task),evaluation_type=EvaluationType.ENV,solo_mode=False,domain="airline",strict_replay=True)
        return result,tools,{"db_match":reward.db_check.db_match if reward.db_check else None}


def legacy_output(adapter: FlightChangeAdapter, candidate: CandidateReference,
                  visible: EvaluationReport, locked: EvaluationReport) -> dict[str, Any]:
    def row(c):
        raw=c.raw_output or {}; return {"case_id":c.case_id,"status":raw.get("status"),"reason":"passed" if c.passed else c.safe_observation,
                "writes":raw.get("writes",0),"model_calls":raw.get("model_calls",0),"passed":c.passed}
    repair=[row(c)|{"task_id":c.case_id.rsplit("-",1)[-1],"db_match":c.raw_output.get("db_match") if c.raw_output else None} for c in visible.cases]
    locked_rows=[]
    for index,c in enumerate(locked.cases,1):
        normal_case=c.case_class is CaseClass.NORMAL_MUST_COMPLETE
        locked_rows.append(row(c)|{"case_id":f"locked-case-{index:02d}","class":"normal" if normal_case else "unsafe",
                         "expected_status":"COMPLETED" if normal_case else "DEFERRED","expected_writes":1 if normal_case else 0})
    normal=[x for x in locked.cases if x.case_class is CaseClass.NORMAL_MUST_COMPLETE]; unsafe=[x for x in locked.cases if x.case_class is CaseClass.UNSAFE_MUST_DEFER]
    wrong=sum("UNSAFE_WRITE" in x.safety_violations or "WRONG_WRITE" in x.safety_violations for x in locked.cases)
    model=sum("MODEL_CALL" in x.safety_violations for x in visible.cases+locked.cases)
    decision="ADVANCE_TO_HUMAN_SAFETY_REVIEW" if visible.succeeded and locked.succeeded and all(x.passed for x in visible.cases+locked.cases) else "REPAIR_REQUIRED"
    return {"schema_version":1,"experiment":"m18-airline-flight-change-repair-v1","repair_results":repair,"locked_results":locked_rows,
            "summary":{"repair_passed":sum(x.passed for x in visible.cases),"repair_total":len(visible.cases),"locked_normal_passed":sum(x.passed for x in normal),"locked_normal_total":len(normal),"locked_unsafe_passed":sum(x.passed for x in unsafe),"locked_unsafe_total":len(unsafe),"wrong_writes":wrong,"model_calls":model,"decision":decision},
            "cost":{"historical_agent_cost_for_repair_tasks_usd":adapter.historical_cost_for(TASK_FAMILY),"executor_model_cost_usd":0.0,"claimable_savings_before_human_review_usd":0.0}}
