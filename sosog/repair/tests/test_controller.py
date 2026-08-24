from __future__ import annotations

import unittest

from sosog.repair.contracts import (
    AttemptStatus,
    CaseClass,
    CaseEvaluation,
    CandidateReference,
    ControllerPolicy,
    EvaluationReport,
    EvaluationTier,
    RepairWorkerResult,
    StopReason,
    SuiteManifest,
)
from sosog.repair.controller import run_repair_loop


def candidate(char: str) -> CandidateReference:
    return CandidateReference(char * 64)


VISIBLE_DIGEST = "1" * 64
LOCKED_DIGEST = "2" * 64


def reports(value, *, visible=0, normal=0, unsafe=0, safety=0, cost=0.0):
    visible_rows = tuple(
        CaseEvaluation(CaseClass.REGRESSION, index < visible) for index in range(2)
    )
    normal_rows = tuple(
        CaseEvaluation(CaseClass.NORMAL_MUST_COMPLETE, index < normal)
        for index in range(2)
    )
    unsafe_rows = tuple(
        CaseEvaluation(
            CaseClass.UNSAFE_MUST_DEFER,
            index < unsafe,
            ("WRITE_BEFORE_VALIDATION",) if index == 0 and safety else (),
        )
        for index in range(2)
    )
    return {
        EvaluationTier.VISIBLE: EvaluationReport(
            value, EvaluationTier.VISIBLE, visible_rows, evaluator_cost=cost,
            suite_digest=VISIBLE_DIGEST,
        ),
        EvaluationTier.LOCKED: EvaluationReport(
            value, EvaluationTier.LOCKED, normal_rows + unsafe_rows,
            suite_digest=LOCKED_DIGEST,
        ),
    }


class Evaluator:
    def __init__(self, values):
        self.values = values

    def suite_manifest(self, tier):
        if tier is EvaluationTier.VISIBLE:
            return SuiteManifest(
                VISIBLE_DIGEST, tier, {CaseClass.REGRESSION: 2}
            )
        return SuiteManifest(
            LOCKED_DIGEST, tier,
            {CaseClass.NORMAL_MUST_COMPLETE: 2, CaseClass.UNSAFE_MUST_DEFER: 2},
        )

    def evaluate(self, value, tier):
        result = self.values[value.fingerprint]
        if isinstance(result, Exception):
            raise result
        return result[tier]


class Worker:
    def __init__(self, values):
        self.values = iter(values)
        self.feedback = []

    def repair(self, value, feedback):
        self.feedback.append(feedback)
        result = next(self.values)
        if isinstance(result, Exception):
            raise result
        return result


class RepairControllerTests(unittest.TestCase):
    def test_perfect_only_advances_to_human_review(self):
        first = candidate("a")
        result = run_repair_loop(
            first,
            Evaluator({first.digest: reports(first, visible=2, normal=2, unsafe=2)}),
            Worker([]),
        )
        self.assertEqual(result.stop_reason, StopReason.PENDING_HUMAN_SAFETY_REVIEW)
        self.assertIn("do not merge or deploy", result.next_human_action)

    def test_empty_suites_do_not_advance(self):
        first = candidate("a")
        result = run_repair_loop(
            first,
            Evaluator({
                first.digest: {
                    EvaluationTier.VISIBLE: EvaluationReport(
                        first, EvaluationTier.VISIBLE, (),
                        suite_digest=VISIBLE_DIGEST,
                    ),
                    EvaluationTier.LOCKED: EvaluationReport(
                        first, EvaluationTier.LOCKED, (),
                        suite_digest=LOCKED_DIGEST,
                    ),
                }
            }),
            Worker([first]),
        )
        self.assertEqual(result.stop_reason, StopReason.EVALUATOR_BLOCKED)

    def test_duplicate_and_two_state_oscillation(self):
        first, second = candidate("a"), candidate("b")
        evaluator = Evaluator({
            first.digest: reports(first),
            second.digest: reports(second, visible=1),
        })
        self.assertEqual(
            run_repair_loop(first, evaluator, Worker([first])).stop_reason,
            StopReason.DUPLICATE_CANDIDATE,
        )
        self.assertEqual(
            run_repair_loop(first, evaluator, Worker([second, first])).stop_reason,
            StopReason.OSCILLATING,
        )

    def test_two_state_feedback_oscillation_stops_with_unique_candidates(self):
        first, second, third, fourth = (
            candidate("a"), candidate("b"), candidate("c"), candidate("d")
        )
        evaluator = Evaluator({
            first.digest: reports(first, visible=0),
            second.digest: reports(second, visible=1),
            third.digest: reports(third, visible=0),
            fourth.digest: reports(fourth, visible=1),
        })
        result = run_repair_loop(
            first, evaluator, Worker([second, third, fourth]),
            ControllerPolicy(stagnation_window=10, oscillation_window=6),
        )
        self.assertEqual(result.stop_reason, StopReason.OSCILLATING)
        self.assertEqual(result.best_candidate, second)

    def test_plateau_and_best_retention(self):
        first, second, third = candidate("a"), candidate("b"), candidate("c")
        evaluator = Evaluator({
            first.digest: reports(first, visible=1),
            second.digest: reports(second),
            third.digest: reports(third),
        })
        result = run_repair_loop(
            first, evaluator, Worker([second, third]),
            ControllerPolicy(stagnation_window=2),
        )
        self.assertEqual(result.stop_reason, StopReason.STAGNATED)
        self.assertEqual(result.best_candidate, first)

    def test_safety_regression_is_rejected(self):
        first, second = candidate("a"), candidate("b")
        evaluator = Evaluator({
            first.digest: reports(first, visible=1),
            second.digest: reports(second, visible=2, safety=1),
        })
        result = run_repair_loop(first, evaluator, Worker([second]))
        self.assertEqual(result.stop_reason, StopReason.REGRESSED_SAFETY)
        self.assertEqual(result.best_candidate, first)

    def test_repeated_gain_only_via_safety_weakening_stops(self):
        first, second, third = candidate("a"), candidate("b"), candidate("c")
        evaluator = Evaluator({
            first.digest: reports(first),
            second.digest: reports(second, visible=1, safety=1),
            third.digest: reports(third, visible=2, safety=1),
        })
        result = run_repair_loop(
            first, evaluator, Worker([second, third]),
            ControllerPolicy(
                stop_on_safety_regression=False,
                no_safe_improvement_window=2,
            ),
        )
        self.assertEqual(result.stop_reason, StopReason.NO_SAFE_IMPROVEMENT)

    def test_attempt_cost_and_time_caps(self):
        first, second = candidate("a"), candidate("b")
        evaluator = Evaluator({
            first.digest: reports(first),
            second.digest: reports(second, visible=1),
        })
        self.assertEqual(
            run_repair_loop(
                first, evaluator, Worker([second]), ControllerPolicy(max_attempts=1)
            ).stop_reason,
            StopReason.ATTEMPT_LIMIT,
        )
        costly = Evaluator({first.digest: reports(first, cost=2)})
        self.assertEqual(
            run_repair_loop(
                first, costly, Worker([second]), ControllerPolicy(max_cost=1)
            ).stop_reason,
            StopReason.COST_LIMIT,
        )
        perfect_but_over_budget = Evaluator({
            first.digest: reports(
                first, visible=2, normal=2, unsafe=2, cost=2
            )
        })
        self.assertEqual(
            run_repair_loop(
                first, perfect_but_over_budget, Worker([]),
                ControllerPolicy(max_cost=1),
            ).stop_reason,
            StopReason.COST_LIMIT,
        )
        ticks = iter([0, 0, 2, 2, 2])
        self.assertEqual(
            run_repair_loop(
                first, evaluator, Worker([second]),
                ControllerPolicy(max_seconds=1), clock=lambda: next(ticks),
            ).stop_reason,
            StopReason.TIME_LIMIT,
        )

    def test_worker_cost_cap_records_unevaluated_candidate(self):
        first, second = candidate("a"), candidate("b")
        result = run_repair_loop(
            first,
            Evaluator({first.digest: reports(first)}),
            Worker([RepairWorkerResult(second, cost=2)]),
            ControllerPolicy(max_cost=1),
        )
        self.assertEqual(result.stop_reason, StopReason.COST_LIMIT)
        self.assertEqual(result.attempts[-1].candidate, second)
        self.assertEqual(result.attempts[-1].status, AttemptStatus.COST_LIMIT)

    def test_repeated_evaluator_failure_and_attempt_exhaustion(self):
        first = candidate("a")
        result = run_repair_loop(
            first, Evaluator({first.digest: RuntimeError("down")}), Worker([]),
            ControllerPolicy(max_evaluator_failures=2),
        )
        self.assertEqual(result.stop_reason, StopReason.EVALUATOR_BLOCKED)
        self.assertEqual(len(result.attempts), 2)
        exhausted = run_repair_loop(
            first, Evaluator({first.digest: RuntimeError("down")}), Worker([]),
            ControllerPolicy(max_attempts=1, max_evaluator_failures=3),
        )
        self.assertEqual(exhausted.stop_reason, StopReason.ATTEMPT_LIMIT)

    def test_worker_failure_is_recorded_and_fail_closed(self):
        first = candidate("a")
        recorded = []
        result = run_repair_loop(
            first,
            Evaluator({first.digest: reports(first)}),
            Worker([RuntimeError("worker unavailable")]),
            recorder=recorded.append,
        )
        self.assertEqual(result.stop_reason, StopReason.WORKER_BLOCKED)
        self.assertEqual(recorded[-1].status, AttemptStatus.WORKER_FAILURE)
        self.assertIn("worker unavailable", recorded[-1].detail)


if __name__ == "__main__":
    unittest.main()
