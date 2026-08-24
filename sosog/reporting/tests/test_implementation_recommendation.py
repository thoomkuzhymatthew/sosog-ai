import json
import unittest
from datetime import date

from promotion_engine.contracts import PromotionAction
from promotion_engine.reporting import render_business_report, render_technical_report
from sosog.economics import (
    CostAssumptions,
    EvidenceQuality,
    Period,
    VolumeInput,
    calculate_fee,
    project_portfolio,
    project_task,
)
from sosog.reporting.implementation_recommendation import (
    ImplementationPath,
    recommend_implementation,
)


class ImplementationRecommendationTests(unittest.TestCase):
    def test_every_internal_action_has_a_path_and_is_json_serializable(self) -> None:
        expected = {
            "FULL_CRYSTALLIZE": ImplementationPath.API_SERVICE,
            "RESPONSE_CRYSTALLIZE": ImplementationPath.API_SERVICE,
            "DECOMPOSE": ImplementationPath.API_SERVICE,
            "LIFT": ImplementationPath.RETAINED_AGENTIC,
            "RETAIN": ImplementationPath.RETAINED_AGENTIC,
            "DROP": ImplementationPath.COLLECT_MORE_EVIDENCE,
        }
        for action in PromotionAction:
            result = recommend_implementation(
                action, client_repo_access=True, repair_status="APPROVED",
                review_status="APPROVED",
            )
            self.assertEqual(result.options[0].path, expected[action.value])
            json.dumps(result.to_dict())
            self.assertTrue(result.human_decision_required)
            self.assertIn("not written, merged, approved, or deployed", result.boundary)

    def test_repo_access_is_necessary_but_not_sufficient_for_merge_request(self) -> None:
        without_access = recommend_implementation(
            "FULL_CRYSTALLIZE", client_repo_access=False,
            repair_status="APPROVED", review_status="APPROVED",
        )
        unreviewed = recommend_implementation(
            "FULL_CRYSTALLIZE", client_repo_access=True,
            repair_status="PENDING_HUMAN_SAFETY_REVIEW",
            review_status="PENDING",
        )
        approved = recommend_implementation(
            "FULL_CRYSTALLIZE", client_repo_access=True,
            repair_status="APPROVED", review_status="APPROVED",
        )
        merge = lambda value: next(o for o in value.options if o.path is ImplementationPath.MERGE_REQUEST)
        self.assertFalse(merge(without_access).eligible)
        self.assertFalse(merge(unreviewed).eligible)
        self.assertTrue(merge(approved).eligible)

    def test_manual_action_has_human_workflow(self) -> None:
        result = recommend_implementation("FULLY_MANUAL", client_repo_access=False)
        self.assertEqual(result.options[0].path, ImplementationPath.HUMAN_WORKFLOW)


class ReportingExtensionTests(unittest.TestCase):
    plan = {"vertical": "x|y", "candidates": [
        {"task_id": "b|2", "action": "RETAIN"},
        {"task_id": "a", "action": "DROP"},
    ]}

    economics = {
        "period": "MONTH", "baseline_cost_usd": "100.00",
        "projected_cost_usd": "80.00",
        "claimed_savings_usd": "20.00", "scenario_savings_usd": "5.00",
        "unavailable_task_count": 1,
        "tasks": [
            {"task_type_id": "reviewed", "action": "FULL_CRYSTALLIZE",
             "availability": "AVAILABLE", "baseline_cost_usd": "50.00",
             "projected_cost_usd": "30.00", "claimed_savings_usd": "20.00",
             "period": "MONTH", "quality": "MEASURED", "confidence": ".9",
             "formula": "measured formula", "assumptions": ["fallback_rate=.1"],
             "sources": ["volume: ledger", "cost: ledger"]},
            {"task_type_id": "unreviewed", "action": "DECOMPOSE",
             "availability": "SCENARIO_ONLY", "baseline_cost_usd": "25.00",
             "projected_cost_usd": "20.00", "claimed_savings_usd": "5.00",
             "period": "MONTH", "quality": "ESTIMATED", "confidence": ".5",
             "formula": "scenario formula", "assumptions": ["tail_fraction=.2"],
             "sources": ["volume: client", "cost: estimate"]},
            {"task_type_id": "rejected", "availability": "UNAVAILABLE",
             "baseline_cost_usd": "25.00", "claimed_savings_usd": None,
             "projected_cost_usd": None, "period": "MONTH",
             "quality": "MEASURED", "confidence": ".8",
             "formula": "unavailable formula", "assumptions": [],
             "sources": ["volume: client", "cost: ledger"], "reason": "rejected"},
        ],
    }

    def test_complete_economics_fee_and_explicit_realized_only(self) -> None:
        economics = dict(self.economics, realized_savings={
            "amount_usd": "3.50", "source": "production ledger",
            "period": "MONTH", "as_of_date": "2026-08-24", "quality": "MEASURED",
        })
        report = render_business_report(self.plan, economics_projections=economics,
            fee_breakdown={"agent_cost_usd": "2", "infrastructure_cost_usd": "1",
                "recorded_cost_usd": "3", "markup_rate": "0.10",
                "markup_usd": ".3", "fee_usd": "3.3"})
        self.assertIn("Portfolio projected claimed savings: **$20.000000**", report)
        self.assertIn("Portfolio scenario-only savings: **$5.000000**", report)
        self.assertIn("Realized savings (measured evidence only): **$3.500000**", report)
        self.assertIn("Measured source: production ledger", report)
        self.assertIn("| $2.000000 | $1.000000 | $3.000000 | 10.0% | $0.300000 | $3.300000 |", report)

    def test_scenario_rejected_and_missing_realized_are_bounded(self) -> None:
        report = render_business_report(self.plan, economics_projections=self.economics)
        self.assertIn("| unreviewed | SCENARIO_ONLY | ESTIMATED; confidence 50.0% | $25.000000 | $20.000000 | Unavailable | $5.000000 |", report)
        self.assertIn("| rejected | UNAVAILABLE | MEASURED; confidence 80.0% | $25.000000 | Unavailable | Unavailable | Unavailable |", report)
        self.assertIn("Realized savings (measured evidence only): **Unavailable**", report)

    def test_malformed_economics_is_unavailable_and_old_call_still_works(self) -> None:
        old = render_business_report(self.plan)
        malformed = render_business_report(self.plan, economics_projections={"claimed_savings_usd": "secret"})
        self.assertIn("**Not calculated.**", old)
        self.assertIn("**Not calculated.**", malformed)
        self.assertNotIn("$0.000000", malformed)

    def test_repair_summary_does_not_render_locked_data(self) -> None:
        summary = {"task_type_id": "safe", "tier": "LOCKED", "status": "REJECTED",
            "reviewed": False, "suite_digest": "a" * 64, "score": {
                "safety_violations": 1, "locked_normal_passed": 2,
                "locked_normal_total": 3, "locked_unsafe_passed": 4,
                "locked_unsafe_total": 5}, "case_id": "DO_NOT_PRINT_CASE",
            "payload": "DO_NOT_PRINT_PAYLOAD", "expected_answer": "DO_NOT_PRINT_EXPECTED",
            "raw_output": "DO_NOT_PRINT_RAW"}
        report = render_technical_report(self.plan, repair_summaries=summary)
        self.assertIn("| safe | LOCKED | REJECTED", report)
        for secret in ("DO_NOT_PRINT_CASE", "DO_NOT_PRINT_PAYLOAD", "DO_NOT_PRINT_EXPECTED", "DO_NOT_PRINT_RAW"):
            self.assertNotIn(secret, report)

    def test_markdown_is_escaped_and_order_is_deterministic(self) -> None:
        first = render_technical_report(self.plan)
        second = render_technical_report({**self.plan, "candidates": list(reversed(self.plan["candidates"]))})
        self.assertEqual(first, second)
        self.assertIn("x\\|y", first)
        self.assertIn("b\\|2", first)

    def test_renders_the_real_economics_and_fee_serialization_contracts(self) -> None:
        projection = project_task(
            VolumeInput(
                "task", "monthly", 100, Period.MONTH, "client ledger",
                date(2026, 8, 24), EvidenceQuality.MEASURED,
            ),
            CostAssumptions(
                "task", 2, 0.1, 0, 0, "billing ledger",
                date(2026, 8, 24), EvidenceQuality.MEASURED, 0.9,
            ),
            PromotionAction.FULL_CRYSTALLIZE,
            {"tier":"LOCKED", "status":"APPROVED", "reviewed":True,
             "source":"review item 42", "fallback_rate":"0.1"},
        )
        fee = calculate_fee([
            {"event_kind":"WORKER", "amount_usd":"2"},
            {"event_kind":"INFRA", "amount_usd":"1"},
        ])
        report = render_business_report(
            self.plan,
            economics_projections=project_portfolio([projection]).to_dict(),
            fee_breakdown=fee.to_dict(),
        )
        self.assertIn("Portfolio projected claimed savings: **$170.000000**", report)
        self.assertIn("client ledger", report)
        self.assertIn("| $2.000000 | $1.000000 | $3.000000 | 10.0%", report)

    def test_bare_realized_savings_and_inconsistent_fee_are_unavailable(self) -> None:
        economics = dict(self.economics, realized_savings_usd="999")
        report = render_business_report(
            self.plan,
            economics_projections=economics,
            fee_breakdown={
                "agent_cost_usd": "2", "infrastructure_cost_usd": "1",
                "recorded_cost_usd": "999", "markup_rate": ".1",
                "markup_usd": ".3", "fee_usd": "999.3",
            },
        )
        self.assertIn("Realized savings (measured evidence only): **Unavailable**", report)
        self.assertNotIn("$999.000000", report)
        self.assertIn("Fee breakdown unavailable", report)


if __name__ == "__main__":
    unittest.main()
