from __future__ import annotations

from decimal import Decimal
import unittest

from sosog.economics.fee import calculate_fee


class FeeTests(unittest.TestCase):
    def test_budget_events_aggregate_and_default_markup_applies_to_cost_only(self):
        result = calculate_fee([
            {"event_kind": "MODEL", "amount_usd": "10.005"},
            {"event_kind": "INFRASTRUCTURE", "amount_usd": "2"},
        ])
        self.assertEqual(result.recorded_cost_usd, Decimal("12.005"))
        self.assertEqual(result.markup_rate, Decimal(".10"))
        self.assertEqual(result.to_dict(), {
            "agent_cost_usd": "10.01",
            "infrastructure_cost_usd": "2",
            "recorded_cost_usd": "12.01",
            "markup_usd": "1.2",
            "fee_usd": "13.21",
            "markup_rate": "0.1",
        })

    def test_all_agent_event_kinds_and_custom_markup(self):
        result = calculate_fee([
            {"event_kind": "WORKER", "amount_usd": "1"},
            {"event_kind": "EVALUATOR", "amount_usd": "2"},
            {"cost_type": "AGENT", "amount_usd": "1"},
            {"category": "INFRA", "amount_usd": "4"},
        ], ".25")
        self.assertEqual(result.agent_cost_usd, 4)
        self.assertEqual(result.infrastructure_cost_usd, 4)
        self.assertEqual(result.fee_usd, 10)

    def test_malformed_events_are_rejected(self):
        for events in (
            [{"event_kind": "MODEL", "amount_usd": -1}],
            [{"event_kind": "CUSTOMER_SAVINGS", "amount_usd": 100}],
            ["not a mapping"],
        ):
            with self.subTest(events=events):
                with self.assertRaises(ValueError):
                    calculate_fee(events)


if __name__ == "__main__":
    unittest.main()
