from __future__ import annotations

import json
import unittest

from promotion_engine import PromotionAction, build_promotion_plan

WRITES = {"write"}


def row(
    task_id: str,
    passed: bool,
    calls: list[tuple[str, dict]],
    *,
    status: str | None = "COMPLETE",
    cost: float | None = None,
) -> dict:
    value = {
        "task_id": task_id,
        "passed": passed,
        "messages": [
            {
                "tool_calls": [
                    {"name": name, "arguments": arguments} for name, arguments in calls
                ]
            }
        ],
    }
    if status is not None:
        value["status"] = status
    if cost is not None:
        value["cost_usd"] = cost
    return value


def action_for(rows: list[dict], *, minimum: int = 5) -> tuple[str, dict]:
    plan = build_promotion_plan(
        "synthetic", rows, write_tools=WRITES, min_complete_runs=minimum
    )
    candidate = plan["candidates"][0]
    return candidate["action"], candidate["evidence"]


class ClassifierTests(unittest.TestCase):
    def test_full_crystallize_requires_one_passing_write_skeleton(self) -> None:
        rows = [
            row("1", True, [("read", {"id": 1}), ("write", {"value": 2})])
            for _ in range(5)
        ]
        action, evidence = action_for(rows)
        self.assertEqual(action, PromotionAction.FULL_CRYSTALLIZE.value)
        self.assertEqual(evidence["n"], 5)
        self.assertEqual(evidence["passes"], 5)
        self.assertEqual(evidence["write_name_patterns"], [["write"]])
        self.assertEqual(evidence["read_prefix"], ['read({"id":1})'])
        self.assertFalse(evidence["review_required"])

    def test_nine_of_ten_can_promote_when_passing_writes_match(self) -> None:
        rows = [row("1", True, [("write", {"value": "right"})]) for _ in range(9)]
        rows.append(row("1", False, [("write", {"value": "wrong"})]))
        action, evidence = action_for(rows)
        self.assertEqual(action, PromotionAction.FULL_CRYSTALLIZE.value)
        self.assertEqual(evidence["pass_rate"], 0.9)

    def test_stable_all_pass_no_write_response_crystallizes(self) -> None:
        rows = [row("1", True, [("read", {"id": 1})]) for _ in range(5)]
        action, evidence = action_for(rows)
        self.assertEqual(action, PromotionAction.RESPONSE_CRYSTALLIZE.value)
        self.assertEqual(evidence["write_name_patterns"], [])
        self.assertEqual(evidence["proposed_next_stage"], "GENERATE_RESPONSE_EXECUTOR")

    def test_unstable_no_write_response_is_retained(self) -> None:
        rows = [row("1", True, [("read", {"id": value})]) for value in range(5)]
        action, evidence = action_for(rows)
        self.assertEqual(action, PromotionAction.RETAIN.value)
        self.assertTrue(evidence["review_required"])

    def test_stable_read_prefix_and_volatile_tail_decomposes(self) -> None:
        rows = [
            row("1", True, [("read", {"id": 1}), ("write", {"value": value})])
            for value in range(5)
        ]
        action, evidence = action_for(rows)
        self.assertEqual(action, PromotionAction.DECOMPOSE.value)
        self.assertEqual(evidence["read_prefix"], ['read({"id":1})'])

    def test_mid_pass_agent_inconsistency_lifts(self) -> None:
        rows = [row("1", True, [("write", {"value": "right"})]) for _ in range(3)]
        rows += [row("1", False, [("write", {"value": "wrong"})]) for _ in range(2)]
        action, evidence = action_for(rows)
        self.assertEqual(action, PromotionAction.LIFT.value)
        self.assertEqual(evidence["pass_rate"], 0.6)
        self.assertEqual(evidence["proposed_next_stage"], "RUN_LIFTING_EXPERIMENT")

    def test_low_pass_candidate_drops(self) -> None:
        rows = [
            row("1", index == 0, [("write", {"value": index})]) for index in range(5)
        ]
        action, evidence = action_for(rows)
        self.assertEqual(action, PromotionAction.DROP.value)
        self.assertFalse(evidence["review_required"])

    def test_coverage_gate_wins_before_treatment_rules(self) -> None:
        rows = [row("1", True, [("write", {"value": 1})]) for _ in range(4)]
        action, evidence = action_for(rows)
        self.assertEqual(action, PromotionAction.RETAIN.value)
        self.assertTrue(evidence["review_required"])
        self.assertEqual(evidence["proposed_next_stage"], "COLLECT_MORE_COMPLETE_RUNS")

    def test_non_complete_and_infrastructure_rows_are_ignored(self) -> None:
        rows = [row("1", True, [("write", {"value": 1})]) for _ in range(5)]
        rows.extend(
            [
                row("1", False, [("write", {"value": 2})], status="ERROR"),
                {
                    "status": "COMPLETE",
                    "termination_reason": "infrastructure_error",
                },
                row("1", False, [], status="RUNNING"),
            ]
        )
        plan = build_promotion_plan("synthetic", rows, write_tools=WRITES)
        self.assertEqual(plan["summary"]["input_rows"], 8)
        self.assertEqual(plan["summary"]["complete_rows"], 5)
        self.assertEqual(plan["summary"]["ignored_rows"], 3)
        self.assertEqual(
            plan["candidates"][0]["action"], PromotionAction.FULL_CRYSTALLIZE.value
        )

    def test_rows_without_complete_status_are_ignored(self) -> None:
        rows = [
            row("1", True, [("write", {"value": 1})], status=None) for _ in range(5)
        ]
        plan = build_promotion_plan("synthetic", rows, write_tools=WRITES)
        self.assertEqual(plan["summary"]["complete_rows"], 0)
        self.assertEqual(plan["candidates"], [])

    def test_passing_no_write_outlier_prevents_full_crystallization(self) -> None:
        rows = [row("1", True, [("write", {"value": "right"})]) for _ in range(4)]
        rows.append(row("1", True, []))
        action, evidence = action_for(rows)
        self.assertEqual(action, PromotionAction.RETAIN.value)
        self.assertTrue(evidence["review_required"])

    def test_artifact_signal_forces_review(self) -> None:
        rows = [row("1", True, [("write", {"value": 1})]) for _ in range(5)]
        rows[0]["annotations"] = {"simulator_disagreement": True}
        action, evidence = action_for(rows)
        self.assertEqual(action, PromotionAction.RETAIN.value)
        self.assertTrue(evidence["review_required"])
        self.assertEqual(evidence["proposed_next_stage"], "REVIEW_TRACE_VALIDITY")

    def test_costs_and_candidate_order_are_deterministic(self) -> None:
        rows = []
        for task_id, cost in (("10", 0.4), ("2", 0.2), ("alpha", 0.6)):
            rows.extend(
                row(task_id, True, [("write", {"value": 1})], cost=cost)
                for _ in range(5)
            )
        plan = build_promotion_plan("synthetic", rows, write_tools=WRITES)
        self.assertEqual(
            [item["task_id"] for item in plan["candidates"]], ["2", "10", "alpha"]
        )
        self.assertEqual(plan["summary"]["mean_complete_cost_usd"], 0.4)
        self.assertEqual(plan["summary"]["observed_cost_usd"], 6.0)
        self.assertEqual(plan["summary"]["min_complete_runs"], 5)
        self.assertEqual(plan["summary"]["promote_pass_rate"], 0.9)
        self.assertEqual(plan["summary"]["action_counts"]["FULL_CRYSTALLIZE"], 3)
        self.assertEqual(plan["summary"]["action_counts"]["DROP"], 0)
        json.dumps(plan)

    def test_flat_call_format_and_json_arguments_are_normalized(self) -> None:
        rows = [
            {
                "task_id": "1",
                "status": "COMPLETE",
                "passed": True,
                "calls": [{"tool_name": "write", "args": '{"b": 2, "a": 1}'}],
            }
            for _ in range(5)
        ]
        action, evidence = action_for(rows)
        self.assertEqual(action, PromotionAction.FULL_CRYSTALLIZE.value)
        self.assertEqual(evidence["write_name_patterns"], [["write"]])

    def test_rejects_invalid_threshold(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 1"):
            build_promotion_plan(
                "synthetic", [], write_tools=WRITES, min_complete_runs=0
            )


if __name__ == "__main__":
    unittest.main()
