from __future__ import annotations

import unittest

from predictor.contracts import TaskFeatures
from predictor.router_v0 import predict
from scripts.run_m17_predictor import build_retail_corpus


class RetailRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = build_retail_corpus()

    def test_all_retail_tasks_are_present(self) -> None:
        self.assertEqual(self.corpus["task_count"], 74)

    def test_no_regression_against_m3_routes(self) -> None:
        mismatches = []
        for item in self.corpus["tasks"]:
            actual = predict(TaskFeatures.from_dict(item["features"])).route.value
            if actual != item["m3_route"]:
                mismatches.append((item["features"]["task_id"], actual, item["m3_route"]))
        self.assertEqual(mismatches, [])

    def test_latest_oracle_records_m11_negative_results(self) -> None:
        by_id = {item["features"]["task_id"]: item for item in self.corpus["tasks"]}
        for task_id in ("87", "100", "112"):
            self.assertEqual(by_id[task_id]["m3_route"], "DECOMPOSE")
            self.assertEqual(by_id[task_id]["oracle_route"], "LEAVE")


if __name__ == "__main__":
    unittest.main()
