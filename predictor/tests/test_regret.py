from __future__ import annotations

import unittest

from predictor.regret import evaluate_task


class RegretTests(unittest.TestCase):
    def test_unsafe_promotion_is_separate_and_penalized(self) -> None:
        row = evaluate_task(
            {
                "features": {
                    "vertical": "synthetic",
                    "task_id": "unsafe",
                    "pass_rate": 1.0,
                    "actual_n": 10,
                    "distinct_passing_skeletons": 1,
                    "m2_baseline_cost": 1.0,
                },
                "oracle_route": "LEAVE",
            }
        )
        self.assertTrue(row["unsafe_promotion"])
        self.assertGreater(row["regret_usd"], 0.0)

    def test_matching_route_has_zero_regret(self) -> None:
        row = evaluate_task(
            {
                "features": {
                    "vertical": "synthetic",
                    "task_id": "ok",
                    "pass_rate": 1.0,
                    "actual_n": 10,
                    "distinct_passing_skeletons": 1,
                    "m2_baseline_cost": 1.0,
                },
                "oracle_route": "PROMOTE",
            }
        )
        self.assertEqual(row["regret_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
