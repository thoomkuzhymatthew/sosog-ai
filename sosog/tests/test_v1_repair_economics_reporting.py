"""Cross-component proof for bounded repair, economics, and reporting."""

from __future__ import annotations

import json
import unittest
from datetime import date

from promotion_engine.contracts import PromotionAction
from promotion_engine.reporting import render_business_report
from sosog.economics import (
    CostAssumptions,
    EvidenceQuality,
    Period,
    VolumeInput,
    calculate_fee,
    project_portfolio,
    project_task,
)
from sosog.repair.contracts import (
    CandidateReference,
    CaseClass,
    CaseEvaluation,
    ControllerPolicy,
    EvaluationReport,
    EvaluationTier,
    RepairWorkerResult,
    StopReason,
    SuiteManifest,
)
from sosog.repair.controller import run_repair_loop
from sosog.reporting import ImplementationPath, recommend_implementation


VISIBLE_DIGEST = "1" * 64
LOCKED_DIGEST = "2" * 64
LOCKED_SECRETS = (
    "locked-owner-case-17",
    "PRIVATE-RESERVATION-991",
    "PRIVATE-EXPECTED-DEFERRAL",
    "PRIVATE-RAW-OUTPUT",
)


class ImprovingEvaluator:
    def suite_manifest(self, tier):
        if tier is EvaluationTier.VISIBLE:
            return SuiteManifest(
                VISIBLE_DIGEST, tier, {CaseClass.REGRESSION: 1}
            )
        return SuiteManifest(
            LOCKED_DIGEST,
            tier,
            {
                CaseClass.NORMAL_MUST_COMPLETE: 1,
                CaseClass.UNSAFE_MUST_DEFER: 1,
            },
        )

    def evaluate(self, candidate, tier):
        repaired = candidate.digest == "b" * 64
        if tier is EvaluationTier.VISIBLE:
            cases = (
                CaseEvaluation(
                    CaseClass.REGRESSION,
                    repaired,
                    invariant_categories=() if repaired else ("STATE_POSTCONDITION",),
                    failure_fingerprint=None if repaired else "visible-state-mismatch",
                    safe_observation=None if repaired else "Preserve the visible state postcondition.",
                ),
            )
            digest = VISIBLE_DIGEST
        else:
            cases = (
                CaseEvaluation(
                    CaseClass.NORMAL_MUST_COMPLETE,
                    repaired,
                    invariant_categories=() if repaired else ("OWNERSHIP",),
                    failure_fingerprint=None if repaired else "private-normal-failure",
                    safe_observation=None if repaired else "Validate ownership before writing.",
                    case_id=LOCKED_SECRETS[0],
                    payload={"reservation": LOCKED_SECRETS[1]},
                    expected_answer=LOCKED_SECRETS[2],
                    raw_output=LOCKED_SECRETS[3],
                ),
                CaseEvaluation(CaseClass.UNSAFE_MUST_DEFER, True),
            )
            digest = LOCKED_DIGEST
        return EvaluationReport(candidate, tier, cases, suite_digest=digest)


class OneRepairWorker:
    def __init__(self):
        self.feedback = None

    def repair(self, candidate, feedback):
        self.feedback = feedback
        serialized = json.dumps(feedback.to_dict(), sort_keys=True)
        for secret in LOCKED_SECRETS:
            if secret in serialized:
                raise AssertionError("locked evidence crossed the worker boundary")
        return RepairWorkerResult(CandidateReference("b" * 64), cost=0.25)


class V1RepairEconomicsReportingTests(unittest.TestCase):
    def test_repair_stops_for_review_then_review_gates_claimed_savings(self):
        worker = OneRepairWorker()
        result = run_repair_loop(
            CandidateReference("a" * 64),
            ImprovingEvaluator(),
            worker,
            ControllerPolicy(max_attempts=2, max_cost=10, max_seconds=10),
        )
        self.assertEqual(result.stop_reason, StopReason.PENDING_HUMAN_SAFETY_REVIEW)
        self.assertTrue(result.best_score.perfect)
        self.assertEqual(result.total_cost, 0.25)
        self.assertIsNotNone(worker.feedback)

        volume = VolumeInput(
            "flight-change", "monthly", 100, Period.MONTH, "client ledger",
            date(2026, 8, 24), EvidenceQuality.MEASURED,
        )
        costs = CostAssumptions(
            "flight-change", 2, 0.1, 0, 0, "billing ledger",
            date(2026, 8, 24), EvidenceQuality.MEASURED, 0.9,
        )
        pending_evidence = {
            "tier": "LOCKED",
            "status": result.stop_reason.value,
            "reviewed": False,
            "source": "locked suite digest " + LOCKED_DIGEST,
            "fallback_rate": "0",
        }
        scenario = project_task(
            volume, costs, PromotionAction.FULL_CRYSTALLIZE, pending_evidence
        )
        scenario_portfolio = project_portfolio([scenario]).to_dict()
        self.assertEqual(scenario_portfolio["claimed_savings_usd"], "0")
        self.assertEqual(scenario_portfolio["scenario_savings_usd"], "190")

        recommendation = recommend_implementation(
            PromotionAction.FULL_CRYSTALLIZE,
            client_repo_access=True,
            repair_status=result.stop_reason.value,
            review_status="PENDING",
        )
        merge_option = next(
            option for option in recommendation.options
            if option.path is ImplementationPath.MERGE_REQUEST
        )
        self.assertFalse(merge_option.eligible)

        repair_summary = {
            "task_type_id": "flight-change",
            "tier": "LOCKED",
            "status": result.stop_reason.value,
            "reviewed": False,
            "suite_digest": LOCKED_DIGEST,
            "best_score": result.best_score.to_dict(),
            "payload": LOCKED_SECRETS[1],
            "raw_output": LOCKED_SECRETS[3],
        }
        report = render_business_report(
            {
                "vertical": "airline",
                "candidates": [{
                    "task_id": "flight-change",
                    "action": PromotionAction.FULL_CRYSTALLIZE.value,
                }],
            },
            economics_projections=scenario_portfolio,
            fee_breakdown=calculate_fee([
                {"event_kind": "WORKER", "amount_usd": "0.25"},
                {"event_kind": "INFRA", "amount_usd": "0.05"},
            ]).to_dict(),
            repair_summaries=repair_summary,
            implementation_recommendations={
                "task_type_id": "flight-change",
                **recommendation.to_dict(),
            },
        )
        self.assertIn("Portfolio projected claimed savings: **$0.000000**", report)
        self.assertIn("Portfolio scenario-only savings: **$190.000000**", report)
        self.assertIn("Realized savings (measured evidence only): **Unavailable**", report)
        for secret in LOCKED_SECRETS:
            self.assertNotIn(secret, report)

        approved = project_task(
            volume,
            costs,
            PromotionAction.FULL_CRYSTALLIZE,
            {**pending_evidence, "status": "APPROVED", "reviewed": True},
        )
        approved_portfolio = project_portfolio([approved]).to_dict()
        self.assertEqual(approved_portfolio["claimed_savings_usd"], "190")
        self.assertEqual(approved_portfolio["scenario_savings_usd"], "0")
        approved_recommendation = recommend_implementation(
            PromotionAction.FULL_CRYSTALLIZE,
            client_repo_access=True,
            repair_status="APPROVED",
            review_status="APPROVED",
        )
        approved_merge = next(
            option for option in approved_recommendation.options
            if option.path is ImplementationPath.MERGE_REQUEST
        )
        self.assertTrue(approved_merge.eligible)


if __name__ == "__main__":
    unittest.main()
