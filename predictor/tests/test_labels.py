from __future__ import annotations

import unittest

from predictor.contracts import FailurePattern, Route, TaskFeatures
from predictor.labels import apply_override, automatic_label


class LabelTests(unittest.TestCase):
    def test_coverage_boundary_requests_review(self) -> None:
        feature = TaskFeatures(
            vertical="synthetic",
            task_id="unknown",
            pass_rate=0.5,
            actual_n=10,
            distinct_passing_skeletons=1,
            failure_pattern=FailurePattern.NEEDS_REVIEW.value,
        )
        label = automatic_label(feature)
        self.assertEqual(label.route, Route.LEAVE)
        self.assertTrue(label.needs_review)

    def test_human_override_is_provenanced(self) -> None:
        feature = TaskFeatures(
            vertical="synthetic",
            task_id="artifact",
            pass_rate=0.5,
            actual_n=10,
            distinct_passing_skeletons=1,
        )
        label = apply_override(
            automatic_label(feature),
            {"route": "LEAVE", "failure_pattern": "artifact", "rationale": "audit"},
        )
        self.assertEqual(label.source, "HUMAN_AUDITED")
        self.assertFalse(label.needs_review)


if __name__ == "__main__":
    unittest.main()
