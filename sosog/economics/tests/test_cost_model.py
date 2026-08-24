from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
import unittest

from sosog.economics.cost_model import (
    ProjectionAvailability,
    project_portfolio,
    project_task,
)
from sosog.economics.inputs import (
    CostAssumptions,
    EvidenceQuality,
    Period,
    VolumeInput,
)


def volume(quality=EvidenceQuality.MEASURED, period=Period.MONTH, task="task"):
    return VolumeInput(
        task, "100 occurrences", "100", period, "client ledger",
        date(2026, 8, 1), quality,
    )


def costs(quality=EvidenceQuality.MEASURED, task="task"):
    return CostAssumptions(
        task, "2", ".10", ".20", ".25", "agent cost ledger",
        date(2026, 8, 1), quality, ".90",
    )


def evidence(*, reviewed=True, fallback_rate=".1"):
    return {
        "tier": "LOCKED",
        "fallback_rate": fallback_rate,
        "reviewed": reviewed,
        "source": "locked suite v1",
    }


class CostModelTests(unittest.TestCase):
    def test_crystallize_actions_use_locked_fallback(self):
        for action in ("FULL_CRYSTALLIZE", "RESPONSE_CRYSTALLIZE"):
            with self.subTest(action=action):
                result = project_task(volume(), costs(), action, evidence())
                self.assertEqual(result.category, "FULLY_CRYSTALLIZABLE")
                self.assertEqual(result.fallback_rate, Decimal(".1"))
                self.assertEqual(result.projected_cost_usd, Decimal("30"))
                self.assertEqual(result.claimed_savings_usd, Decimal("170"))

    def test_decompose_math_is_gated_by_locked_review(self):
        result = project_task(volume(), costs(), "DECOMPOSE", evidence())
        self.assertEqual(result.projected_cost_usd, Decimal("70"))
        self.assertEqual(result.claimed_savings_usd, Decimal("130"))
        self.assertIs(result.availability, ProjectionAvailability.AVAILABLE)
        missing = project_task(volume(), costs(), "DECOMPOSE")
        self.assertIs(missing.availability, ProjectionAvailability.UNAVAILABLE)
        self.assertIsNone(missing.claimed_savings_usd)

    def test_no_savings_categories_never_claim_savings(self):
        cases = (
            ("LIFT", "FULLY_AGENTIC"),
            ("RETAIN", "FULLY_AGENTIC"),
            ("DROP", "INSUFFICIENT_EVIDENCE"),
            ("FULLY_MANUAL", "FULLY_MANUAL"),
        )
        for action, category in cases:
            with self.subTest(action=action):
                result = project_task(volume(), costs(), action)
                self.assertEqual(result.category, category)
                self.assertEqual(result.claimed_savings_usd, 0)
                self.assertEqual(result.projected_cost_usd, result.baseline_cost_usd)

    def test_missing_invalid_or_unreviewed_evidence_fails_closed(self):
        invalid_values = (
            None,
            {"tier": "VISIBLE", "fallback_rate": ".1", "source": "wrong"},
            {"tier": "LOCKED", "fallback_rate": "1.1", "source": "bad"},
            {"tier": "LOCKED", "passed": "1.5", "total": "2", "source": "bad"},
            {"tier": "LOCKED", "fallback_rate": ".1", "reviewed": "yes", "source": "bad"},
            {"tier": "LOCKED", "fallback_rate": ".1", "status": "REJECTED", "source": "bad"},
            {"tier": "LOCKED", "fallback_rate": ".1", "reviewed": True,
             "status": "PENDING_HUMAN_SAFETY_REVIEW", "source": "bad"},
        )
        for value in invalid_values:
            with self.subTest(value=value):
                result = project_task(volume(), costs(), "FULL_CRYSTALLIZE", value)
                self.assertIs(result.availability, ProjectionAvailability.UNAVAILABLE)
                self.assertIsNone(result.projected_cost_usd)
                self.assertIsNone(result.claimed_savings_usd)
        scenario = project_task(
            volume(), costs(), "FULL_CRYSTALLIZE", evidence(reviewed=False)
        )
        self.assertIs(scenario.availability, ProjectionAvailability.SCENARIO_ONLY)
        self.assertEqual(scenario.savings_kind, "PROJECTED")
        self.assertIn("scenario", scenario.reason.lower())

    def test_review_never_turns_projection_into_realized_savings(self):
        value = evidence() | {"realized": True}
        result = project_task(volume(), costs(), "FULL_CRYSTALLIZE", value)
        self.assertEqual(result.savings_kind, "PROJECTED")

    def test_estimated_quality_caps_confidence_for_either_estimated_input(self):
        for volume_quality, cost_quality in (
            (EvidenceQuality.ESTIMATED, EvidenceQuality.MEASURED),
            (EvidenceQuality.MEASURED, EvidenceQuality.ESTIMATED),
        ):
            with self.subTest(volume=volume_quality, cost=cost_quality):
                result = project_task(
                    volume(volume_quality, Period.QUARTER), costs(cost_quality),
                    "DECOMPOSE", evidence(),
                )
                self.assertIs(result.quality, EvidenceQuality.ESTIMATED)
                self.assertEqual(result.confidence, Decimal(".5"))
                self.assertEqual(result.period, "QUARTER")

    def test_portfolio_reconciles_claimed_scenario_and_unavailable_tasks(self):
        reviewed = project_task(
            volume(task="z"), costs(task="z"), "DECOMPOSE", evidence()
        )
        scenario = project_task(
            volume(task="a"), costs(task="a"), "FULL_CRYSTALLIZE",
            evidence(reviewed=False),
        )
        portfolio = project_portfolio([reviewed, scenario])
        self.assertEqual([item.task_type_id for item in portfolio.tasks], ["a", "z"])
        self.assertEqual(portfolio.baseline_cost_usd, 400)
        self.assertEqual(portfolio.projected_cost_usd, 270)
        self.assertEqual(portfolio.claimed_savings_usd, 130)
        self.assertEqual(portfolio.scenario_savings_usd, 170)
        self.assertEqual(portfolio.scenario_task_count, 1)

    def test_portfolio_periods_and_serialization_are_deterministic(self):
        first = project_task(
            volume(task="a"), costs(task="a"), "DECOMPOSE", evidence()
        )
        second = project_task(volume(task="b"), costs(task="b"), "RETAIN")
        forward = project_portfolio([first, second]).to_dict()
        reverse = project_portfolio([second, first]).to_dict()
        self.assertEqual(
            json.dumps(forward, sort_keys=True), json.dumps(reverse, sort_keys=True)
        )
        with self.assertRaisesRegex(ValueError, "periods"):
            project_portfolio([
                first,
                project_task(
                    volume(period=Period.YEAR, task="c"), costs(task="c"), "RETAIN"
                ),
            ])


if __name__ == "__main__":
    unittest.main()
