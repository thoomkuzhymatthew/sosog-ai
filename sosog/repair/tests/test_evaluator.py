from __future__ import annotations

import json
import unittest

from sosog.repair.contracts import (
    CaseClass,
    CaseEvaluation,
    CandidateReference,
    EvaluationReport,
    EvaluationTier,
    StructuredScore,
    SuiteManifest,
)
from sosog.repair.evaluator import is_better, reports_to_feedback


def candidate(char: str) -> CandidateReference:
    return CandidateReference(char * 64)


VISIBLE_DIGEST = "1" * 64
LOCKED_DIGEST = "2" * 64


class EvaluatorTests(unittest.TestCase):
    def test_score_order_is_safety_first_and_cost_last(self):
        base = StructuredScore(0, 1, 2, 1, 2, 1, 2, 10)
        self.assertFalse(
            is_better(StructuredScore(1, 2, 2, 2, 2, 2, 2, 0), base)
        )
        self.assertTrue(
            is_better(StructuredScore(0, 2, 2, 0, 2, 0, 2, 99), base)
        )
        self.assertTrue(
            is_better(StructuredScore(0, 1, 2, 1, 2, 1, 2, 9), base)
        )

    def test_feedback_is_deterministic_and_does_not_leak_locked_evidence(self):
        value = candidate("a")
        visible = EvaluationReport(
            value,
            EvaluationTier.VISIBLE,
            (CaseEvaluation(CaseClass.REGRESSION, True),),
            suite_digest=VISIBLE_DIGEST,
        )
        locked = EvaluationReport(
            value,
            EvaluationTier.LOCKED,
            (
                CaseEvaluation(
                    CaseClass.NORMAL_MUST_COMPLETE,
                    True,
                    case_id="normal-secret-id",
                    payload={"private-field": "payload-secret"},
                    expected_answer="expected-secret",
                    raw_output="raw-success-secret",
                ),
                CaseEvaluation(
                    CaseClass.UNSAFE_MUST_DEFER,
                    False,
                    ("WRITE",),
                    ("OWNERSHIP",),
                    "private-failure-id",
                    "Check ownership before writing.",
                    "unsafe-secret-id",
                    {"secret-payload": 1},
                    "expected-unsafe-secret",
                    "raw-unsafe-secret",
                ),
            ),
            suite_digest=LOCKED_DIGEST,
        )
        first = reports_to_feedback(visible, locked)
        second = reports_to_feedback(visible, locked)
        self.assertEqual(first.fingerprint, second.fingerprint)
        serialized = json.dumps(first.to_dict(), sort_keys=True)
        for secret in (
            "normal-secret-id", "private-field", "payload-secret",
            "expected-secret", "raw-success-secret", "unsafe-secret-id",
            "secret-payload", "expected-unsafe-secret", "raw-unsafe-secret",
            "private-failure-id",
        ):
            self.assertNotIn(secret, serialized)

    def test_sanitizer_rejects_worker_text_that_echoes_locked_payload(self):
        value = candidate("a")
        visible = EvaluationReport(
            value, EvaluationTier.VISIBLE,
            (CaseEvaluation(CaseClass.REGRESSION, True),),
            suite_digest=VISIBLE_DIGEST,
        )
        locked = EvaluationReport(
            value, EvaluationTier.LOCKED,
            (
                CaseEvaluation(CaseClass.NORMAL_MUST_COMPLETE, True),
                CaseEvaluation(
                    CaseClass.UNSAFE_MUST_DEFER,
                    False,
                    invariant_categories=("PAYLOAD-SECRET",),
                    payload={"value": "PAYLOAD-SECRET"},
                ),
            ),
            suite_digest=LOCKED_DIGEST,
        )
        with self.assertRaisesRegex(ValueError, "contains locked evidence"):
            reports_to_feedback(visible, locked)

    def test_empty_suites_are_not_perfect(self):
        value = candidate("a")
        feedback = reports_to_feedback(
            EvaluationReport(
                value, EvaluationTier.VISIBLE, (), suite_digest=VISIBLE_DIGEST
            ),
            EvaluationReport(
                value, EvaluationTier.LOCKED, (), suite_digest=LOCKED_DIGEST
            ),
        )
        self.assertFalse(feedback.score.perfect)

    def test_feedback_requires_matching_candidate_and_tiers(self):
        first, second = candidate("a"), candidate("b")
        visible = EvaluationReport(
            first, EvaluationTier.VISIBLE, (), suite_digest=VISIBLE_DIGEST
        )
        locked = EvaluationReport(
            second, EvaluationTier.LOCKED, (), suite_digest=LOCKED_DIGEST
        )
        with self.assertRaisesRegex(ValueError, "same candidate"):
            reports_to_feedback(visible, locked)
        with self.assertRaisesRegex(ValueError, "visible then locked"):
            reports_to_feedback(
                EvaluationReport(
                    first, EvaluationTier.LOCKED, (), suite_digest=LOCKED_DIGEST
                ),
                EvaluationReport(
                    first, EvaluationTier.VISIBLE, (), suite_digest=VISIBLE_DIGEST
                ),
            )

    def test_manifest_is_payload_free_and_matches_exact_suite_shape(self):
        manifest = SuiteManifest(
            LOCKED_DIGEST,
            EvaluationTier.LOCKED,
            {CaseClass.NORMAL_MUST_COMPLETE: 1, CaseClass.UNSAFE_MUST_DEFER: 1},
        )
        serialized = json.dumps(manifest.to_dict(), sort_keys=True)
        self.assertNotIn("payload", serialized)
        value = candidate("a")
        report = EvaluationReport(
            value,
            EvaluationTier.LOCKED,
            (
                CaseEvaluation(CaseClass.NORMAL_MUST_COMPLETE, True),
                CaseEvaluation(CaseClass.UNSAFE_MUST_DEFER, True),
            ),
            suite_digest=LOCKED_DIGEST,
        )
        self.assertTrue(manifest.matches(report))


if __name__ == "__main__":
    unittest.main()
