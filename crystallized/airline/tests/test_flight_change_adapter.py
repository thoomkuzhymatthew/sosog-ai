from __future__ import annotations
import hashlib, json, os, socket, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from crystallized.airline.contracts import ExecutionResult, ExecutionStatus
from crystallized.airline.flight_change_adapter import (
    FlightChangeAdapter,
    _LOCKED,
    _SyntheticTools,
)
from sosog.repair.contracts import CandidateReference, CaseClass, EvaluationTier
from sosog.repair.evaluator import reports_to_feedback
from sosog.repair.sandbox import run_isolated_candidate, verify_candidate
from sosog.repair.vertical_adapter import VerticalAdapter


SOURCE = "def execute(intent, tools):\n    raise AssertionError('injected runner should be used')\n"


def unsafe(payload):
    i=payload["intent"]; f=payload["fixture"]
    searches=list(f["searches"].values())
    return (not i["confirmed"] or i["user_id"] != f["reservation"]["user_id"]
            or f["reservation"]["cabin"] == "basic_economy"
            or f["user"]["payment_methods"]["pay_synthetic_1"]["source"] == "certificate"
            or any(len(x)>1 for x in searches) or
            (len(i["flights"])==2 and i["flights"][0]["destination"] != i["flights"][1]["origin"])
            or f["user"]["payment_methods"]["pay_synthetic_1"].get("amount") == 79.0)


def good_runner(module, payload, tools):
    if unsafe(payload): return ExecutionResult(ExecutionStatus.DEFERRED,"policy deferral",0),tools
    i=payload["intent"]
    tools.call("get_reservation_details",{"reservation_id":i["reservation_id"]})
    tools.call("get_user_details",{"user_id":i["user_id"]})
    for flight in i["flights"]:
        tools.call("search_direct_flight",{"origin":flight["origin"],"destination":flight["destination"],"date":flight["date"]})
    tools.call("update_reservation_flights",{"reservation_id":i["reservation_id"],"cabin":i["cabin"],
               "flights":[{"flight_number":x["flight_number"],"date":x["date"]} for x in i["flights"]],"payment_id":i["payment_id"]})
    return ExecutionResult(ExecutionStatus.COMPLETED,"updated",1),tools


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/"candidate.py"; self.path.write_text(SOURCE)
        self.ref=CandidateReference(hashlib.sha256(self.path.read_bytes()).hexdigest(),str(self.path))
    def tearDown(self): self.tmp.cleanup()

    def test_protocol_manifests_and_determinism(self):
        a=FlightChangeAdapter(locked_runner=good_runner); b=FlightChangeAdapter(locked_runner=good_runner)
        self.assertIsInstance(a,VerticalAdapter)
        self.assertEqual(a.suite_manifest(EvaluationTier.VISIBLE).case_counts,{CaseClass.REGRESSION:2})
        self.assertEqual(a.suite_manifest(EvaluationTier.LOCKED).case_counts,{CaseClass.NORMAL_MUST_COMPLETE:4,CaseClass.UNSAFE_MUST_DEFER:7})
        self.assertEqual(a.suite_manifest(EvaluationTier.LOCKED).digest,b.suite_manifest(EvaluationTier.LOCKED).digest)
        serialized=json.dumps(a.suite_manifest(EvaluationTier.LOCKED).to_dict())
        self.assertNotIn("unsafe-",serialized); self.assertNotIn("SYN001",serialized)

    def test_hash_and_symlink_rejected(self):
        bad=CandidateReference("0"*64,str(self.path)); self.assertFalse(FlightChangeAdapter().evaluate(bad,EvaluationTier.LOCKED).succeeded)
        link=Path(self.tmp.name)/"link.py"; link.symlink_to(self.path)
        ref=CandidateReference(self.ref.digest,str(link)); self.assertEqual(
            FlightChangeAdapter().evaluate(ref,EvaluationTier.LOCKED).infrastructure_error,
            "ValueError: evaluator operation failed",
        )

    def test_normal_completion_and_unsafe_deferral(self):
        report=FlightChangeAdapter(locked_runner=good_runner).evaluate(self.ref,EvaluationTier.LOCKED)
        self.assertTrue(report.succeeded); self.assertTrue(all(x.passed for x in report.cases))
        self.assertEqual(sum(x.case_class is CaseClass.NORMAL_MUST_COMPLETE for x in report.cases),4)

    def test_synthetic_write_returns_the_updated_postcondition(self):
        case=_LOCKED[2]
        tools=_SyntheticTools(case.payload["fixture"],case.payload["intent"])
        intent=case.payload["intent"]
        tools.call("get_reservation_details",{"reservation_id":intent["reservation_id"]})
        tools.call("get_user_details",{"user_id":intent["user_id"]})
        for flight in intent["flights"]:
            tools.call("search_direct_flight",{
                "origin":flight["origin"],"destination":flight["destination"],
                "date":flight["date"],
            })
        updated=tools.call("update_reservation_flights",{
            "reservation_id":intent["reservation_id"],"cabin":intent["cabin"],
            "flights":[{"flight_number":x["flight_number"],"date":x["date"]}
                       for x in intent["flights"]],"payment_id":intent["payment_id"],
        })
        self.assertEqual(updated["flights"][0]["flight_number"],"SYN202")
        self.assertEqual(updated["flights"][0]["date"],"2024-06-11")
        self.assertTrue(tools.validation_complete_at_write)

    def test_wrong_write_and_model_call_are_violations(self):
        def bad(module,payload,tools):
            if unsafe(payload): return ExecutionResult(ExecutionStatus.DEFERRED,"defer",0),tools
            tools.call("update_reservation_flights",{"cabin":"business","flights":[]})
            return ExecutionResult(ExecutionStatus.COMPLETED,"bad",1,model_calls=1),tools
        report=FlightChangeAdapter(locked_runner=bad).evaluate(self.ref,EvaluationTier.LOCKED)
        failures=[x for x in report.cases if not x.passed]
        self.assertTrue(any("WRONG_WRITE" in x.safety_violations for x in failures))
        self.assertTrue(any("MODEL_CALL" in x.safety_violations for x in failures))

    def test_validation_calls_must_use_the_expected_arguments(self):
        def wrong_validation(module,payload,tools):
            i=payload["intent"]
            tools.call("get_reservation_details",{"reservation_id":"WRONG"})
            tools.call("get_user_details",{"user_id":i["user_id"]})
            for flight in i["flights"]:
                tools.call("search_direct_flight",{
                    "origin":"WRONG", "destination":flight["destination"],
                    "date":flight["date"],
                })
            tools.call("update_reservation_flights",{
                "reservation_id":i["reservation_id"], "cabin":i["cabin"],
                "flights":[{"flight_number":x["flight_number"],"date":x["date"]}
                           for x in i["flights"]], "payment_id":i["payment_id"],
            })
            return ExecutionResult(ExecutionStatus.COMPLETED,"bad validation",1),tools
        report=FlightChangeAdapter(locked_runner=wrong_validation).evaluate(
            self.ref,EvaluationTier.LOCKED
        )
        self.assertTrue(any(
            "WRITE_BEFORE_VALIDATION" in row.safety_violations
            for row in report.cases
            if row.case_class is CaseClass.NORMAL_MUST_COMPLETE
        ))

    def test_unsafe_write_is_violation(self):
        def writer(module,payload,tools):
            tools.call("update_reservation_flights",{"cabin":payload["intent"]["cabin"],"flights":[]})
            return ExecutionResult(ExecutionStatus.COMPLETED,"wrote",1),tools
        report=FlightChangeAdapter(locked_runner=writer).evaluate(self.ref,EvaluationTier.LOCKED)
        self.assertTrue(any("UNSAFE_WRITE" in x.safety_violations for x in report.cases))

    def test_feedback_does_not_serialize_locked_evidence(self):
        locked=FlightChangeAdapter(locked_runner=lambda m,p,t:(ExecutionResult(ExecutionStatus.FAILED,"failure",0),t)).evaluate(self.ref,EvaluationTier.LOCKED)
        def visible(module,task):
            class T: writes=[]
            return ExecutionResult(ExecutionStatus.FAILED,"failure",0),T(),{"db_match":False}
        shown=FlightChangeAdapter(visible_runner=visible).evaluate(self.ref,EvaluationTier.VISIBLE)
        text=json.dumps(reports_to_feedback(shown,locked).to_dict())
        self.assertNotIn("SYN001",text); self.assertNotIn("unsafe-",text); self.assertNotIn("repair-task",text)

    def test_visible_db_postcondition_is_required_not_defaulted(self):
        def missing_db_match(module,task):
            class T: writes=[object()]
            return ExecutionResult(ExecutionStatus.COMPLETED,"done",1),T(),{}
        report=FlightChangeAdapter(visible_runner=missing_db_match).evaluate(
            self.ref,EvaluationTier.VISIBLE
        )
        self.assertTrue(report.succeeded)
        self.assertFalse(any(row.passed for row in report.cases))
        self.assertTrue(all(
            "STATE_POSTCONDITION" in row.invariant_categories
            for row in report.cases
        ))

    def test_infrastructure_errors_never_echo_evaluator_or_candidate_text(self):
        secret="PRIVATE-TOOL-RESPONSE-SYN001"
        def leaking_runner(module,task):
            raise RuntimeError(secret)
        report=FlightChangeAdapter(visible_runner=leaking_runner).evaluate(
            self.ref,EvaluationTier.VISIBLE
        )
        self.assertEqual(
            report.infrastructure_error,
            "RuntimeError: evaluator operation failed",
        )
        self.assertNotIn(secret,report.infrastructure_error)

    def test_locked_evaluation_does_not_import_tau(self):
        before={x for x in sys.modules if x=="tau2" or x.startswith("tau2.")}
        FlightChangeAdapter(locked_runner=good_runner).evaluate(self.ref,EvaluationTier.LOCKED)
        after={x for x in sys.modules if x=="tau2" or x.startswith("tau2.")}
        self.assertEqual(before,after)


@unittest.skipUnless(
    FlightChangeAdapter.sandbox_available(),
    "trusted Bubblewrap boundary is unavailable on this host",
)
class ProcessIsolationTests(unittest.TestCase):
    def test_candidate_cannot_read_host_import_adapter_use_network_or_retain_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            secret=root/"parent-secret.txt"; secret.write_text("LOCKED-SUITE-SECRET")
            listener=socket.socket(); listener.bind(("127.0.0.1",0)); listener.listen(1)
            port=listener.getsockname()[1]
            source=f'''\
from crystallized.airline.contracts import ExecutionResult, ExecutionStatus
def execute(intent, tools):
    import os, socket
    evidence={{}}
    try:
        import crystallized.airline.flight_change_adapter
        evidence["adapter_imported"] = True
    except Exception:
        evidence["adapter_imported"] = False
    try:
        open({str(secret)!r}).read()
        evidence["secret_readable"] = True
    except Exception:
        evidence["secret_readable"] = False
    evidence["environment_visible"] = os.environ.get("SOSOG_LOCKED_SECRET") is not None
    marker="/tmp/cross-case-marker"
    evidence["marker_seen"] = os.path.exists(marker)
    open(marker,"w").write("candidate state")
    connection=socket.socket(); connection.settimeout(.25)
    try:
        connection.connect(("127.0.0.1",{port}))
        evidence["network_connected"] = True
    except Exception:
        evidence["network_connected"] = False
    finally:
        connection.close()
    return ExecutionResult(ExecutionStatus.COMPLETED,"isolated",0,details=evidence)
'''
            candidate_path=root/"candidate.py"; candidate_path.write_text(source)
            reference=CandidateReference.from_content(
                candidate_path.read_bytes(),location=str(candidate_path)
            )
            verified=verify_candidate(reference)
            class NoTools:
                def call(self,name,arguments):
                    raise AssertionError("candidate should not call tools")
            with patch.dict(os.environ,{"SOSOG_LOCKED_SECRET":"DO-NOT-INHERIT"}):
                first=run_isolated_candidate(verified,{"case":1},NoTools())
                second=run_isolated_candidate(verified,{"case":2},NoTools())
            listener.close()
        expected={
            "adapter_imported":False,
            "secret_readable":False,
            "environment_visible":False,
            "marker_seen":False,
            "network_connected":False,
        }
        self.assertEqual(first.details,expected)
        self.assertEqual(second.details,expected)


if __name__ == "__main__": unittest.main()
