from __future__ import annotations
import hashlib, json, sys, tempfile, unittest
from pathlib import Path

from crystallized.airline.contracts import ExecutionResult, ExecutionStatus
from crystallized.airline.flight_change_adapter import FlightChangeAdapter
from sosog.repair.contracts import CandidateReference, CaseClass, EvaluationTier
from sosog.repair.evaluator import reports_to_feedback
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
        ref=CandidateReference(self.ref.digest,str(link)); self.assertIn("non-symlink",FlightChangeAdapter().evaluate(ref,EvaluationTier.LOCKED).infrastructure_error)

    def test_normal_completion_and_unsafe_deferral(self):
        report=FlightChangeAdapter(locked_runner=good_runner).evaluate(self.ref,EvaluationTier.LOCKED)
        self.assertTrue(report.succeeded); self.assertTrue(all(x.passed for x in report.cases))
        self.assertEqual(sum(x.case_class is CaseClass.NORMAL_MUST_COMPLETE for x in report.cases),4)

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

    def test_locked_evaluation_does_not_import_tau(self):
        before={x for x in sys.modules if x=="tau2" or x.startswith("tau2.")}
        FlightChangeAdapter(locked_runner=good_runner).evaluate(self.ref,EvaluationTier.LOCKED)
        after={x for x in sys.modules if x=="tau2" or x.startswith("tau2.")}
        self.assertEqual(before,after)


if __name__ == "__main__": unittest.main()
