from __future__ import annotations

import unittest

from predictor.contracts import FailurePattern, Route, TaskFeatures
from predictor.router_v0 import predict


def feature(**updates) -> TaskFeatures:
    values = {
        "vertical": "synthetic",
        "task_id": "1",
        "pass_rate": 0.5,
        "actual_n": 10,
        "distinct_passing_skeletons": 1,
        "m2_baseline_cost": 1.0,
    }
    values.update(updates)
    return TaskFeatures(**values)


class RouterTests(unittest.TestCase):
    def test_all_firing_routes(self) -> None:
        cases = [
            (feature(pass_rate=0.9), Route.PROMOTE),
            (
                feature(
                    pass_rate=1.0,
                    distinct_passing_skeletons=2,
                    prefix_ends_before_write=True,
                ),
                Route.DECOMPOSE,
            ),
            (
                feature(failure_pattern=FailurePattern.AGENT_WANDERED.value),
                Route.LIFT,
            ),
            (feature(artifact_flag=True), Route.LEAVE),
            (feature(pass_rate=0.2, distinct_passing_skeletons=0), Route.DROP),
        ]
        for value, route in cases:
            with self.subTest(route=route):
                self.assertEqual(predict(value).route, route)

    def test_gated_parser_is_reserved(self) -> None:
        values = [
            feature(pass_rate=rate, distinct_passing_skeletons=skeletons)
            for rate in (0.0, 0.5, 0.9, 1.0)
            for skeletons in (0, 1, 2)
        ]
        self.assertNotIn(Route.GATED_PARSER, {predict(item).route for item in values})


if __name__ == "__main__":
    unittest.main()
