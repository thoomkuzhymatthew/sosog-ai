from __future__ import annotations

import unittest

from predictor.contracts import FailurePattern
from predictor.features import extract_task_features


WRITES = {"write"}


def row(ok: bool, calls: list[tuple[str, dict]]) -> dict:
    return {
        "task_id": "x",
        "passed": ok,
        "messages": [
            {
                "tool_calls": [
                    {"name": name, "arguments": arguments} for name, arguments in calls
                ]
            }
        ],
    }


class FeatureTests(unittest.TestCase):
    def test_common_read_prefix_stops_before_common_write(self) -> None:
        runs = [
            row(True, [("read", {"id": 1}), ("write", {"value": value})])
            for value in (1, 1, 2)
        ]
        feature = extract_task_features("synthetic", "x", runs, write_tools=WRITES)
        self.assertEqual(feature.longest_common_read_prefix_len, 1)
        self.assertTrue(feature.prefix_ends_before_write)
        self.assertEqual(feature.distinct_passing_skeletons, 2)

    def test_same_wrong_write_is_agent_wandered(self) -> None:
        runs = [
            row(True, [("read", {"id": 1}), ("write", {"value": "right"})]),
            row(False, [("read", {"id": 1}), ("write", {"value": "wrong"})]),
            row(False, [("read", {"id": 1}), ("write", {"value": "wrong"})]),
        ]
        feature = extract_task_features("synthetic", "x", runs, write_tools=WRITES)
        self.assertEqual(feature.failure_pattern, FailurePattern.AGENT_WANDERED.value)

    def test_explicit_artifact_annotation_wins(self) -> None:
        runs = [row(False, [("write", {"value": 1})])]
        runs[0]["annotations"] = {"simulator_disagreement": True}
        feature = extract_task_features("synthetic", "x", runs, write_tools=WRITES)
        self.assertTrue(feature.artifact_flag)
        self.assertEqual(feature.failure_pattern, FailurePattern.ARTIFACT.value)


if __name__ == "__main__":
    unittest.main()
