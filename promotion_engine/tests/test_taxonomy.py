from __future__ import annotations

import unittest

from promotion_engine.contracts import PromotionAction
from promotion_engine.taxonomy import client_category_for


class TaxonomyTests(unittest.TestCase):
    def test_every_internal_action_maps_to_reporting_category(self) -> None:
        expected = {
            PromotionAction.FULL_CRYSTALLIZE: "FULLY_CRYSTALLIZABLE",
            PromotionAction.RESPONSE_CRYSTALLIZE: "FULLY_CRYSTALLIZABLE",
            PromotionAction.DECOMPOSE: "DECOMPOSABLE",
            PromotionAction.LIFT: "FULLY_AGENTIC",
            PromotionAction.RETAIN: "FULLY_AGENTIC",
            PromotionAction.DROP: "INSUFFICIENT_EVIDENCE",
        }
        self.assertEqual(set(expected), set(PromotionAction))
        for action, category in expected.items():
            with self.subTest(action=action):
                self.assertEqual(client_category_for(action), category)
                self.assertEqual(client_category_for(action.value), category)

    def test_invalid_action_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            client_category_for("FULLY_MANUAL")


if __name__ == "__main__":
    unittest.main()
