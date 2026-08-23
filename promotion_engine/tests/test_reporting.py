from promotion_engine.reporting import render_business_report, render_technical_report


def _flat_plan() -> dict:
    return {
        "vertical": "airline",
        "summary": {
            "action_counts": {"FULL_CRYSTALLIZE": 1, "DECOMPOSE": 1},
            "observed_cost_usd": 0.91,
            "candidate_cost_usd": 0.44,
        },
        "candidates": [
            {
                "task_id": "task-20",
                "action": "DECOMPOSE",
                "pass_rate": 0.8,
                "actual_n": 10,
                "mean_cost_usd": 0.03,
                "confidence": "medium",
                "reason": "Two stable write families",
                "review_required": True,
                "write_name_patterns": ["update_booking", "cancel_booking"],
                "proposed_next_stage": "Generate family-specific executors",
            },
            {
                "task_id": "task-10",
                "action": "FULL_CRYSTALLIZE",
                "pass_rate": 1.0,
                "actual_n": 8,
                "mean_cost_usd": 0.02,
                "confidence": 0.95,
                "reason": "Stable action sequence",
                "review_required": False,
                "write_name_patterns": [],
                "proposed_next_stage": "Generate deterministic executor",
            },
        ],
    }


def test_technical_report_includes_evidence_routes_and_boundaries() -> None:
    report = render_technical_report(_flat_plan())

    assert "# Technical Promotion Report" in report
    assert "| task-10 | 100.0% | 8 | $0.020000 | 95.0% |" in report
    assert report.index("task-10") < report.index("task-20")
    assert "| FULL_CRYSTALLIZE | 1 |" in report
    assert "| DECOMPOSE | 1 |" in report
    assert "Two stable write families" in report
    assert "Required | cancel_booking, update_booking" in report
    assert "## Suggested Code-Change Stage" in report
    assert "Generate deterministic executor" in report


def test_renderers_accept_nested_classifier_evidence() -> None:
    plan = {
        "vertical": "retail",
        "summary": {"mean_complete_cost_usd": 0.0125},
        "candidates": [
            {
                "task_id": "5",
                "action": "LIFT",
                "evidence": {
                    "n": 12,
                    "pass_rate": 0.75,
                    "mean_cost_usd": 0.004,
                    "confidence": "high",
                    "reason": "Parser boundary remains uncertain",
                    "review_required": True,
                    "write_name_patterns": ["return_item"],
                    "proposed_next_stage": "Lift the parser and rerun held-out tests",
                },
            }
        ],
    }

    technical = render_technical_report(plan)
    business = render_business_report(plan)

    assert "| 5 | 75.0% | 12 | $0.004000 | high |" in technical
    assert "| LIFT | 1 |" in technical
    assert "Observed mean cost per complete benchmark run: **$0.012500**" in business
    assert "Lift the parser and rerun held-out tests" in business


def test_business_report_does_not_turn_benchmark_cost_into_savings() -> None:
    report = render_business_report(_flat_plan())

    assert "## Observed Benchmark Cost" in report
    assert "Observed benchmark cost recorded by the plan: **$0.910000**" in report
    assert "## Customer Savings Projection" in report
    assert "**Not calculated.**" in report
    assert "not projected customer savings" in report
    assert "customer workload volume" in report


def test_reports_are_deterministic() -> None:
    plan = _flat_plan()

    assert render_technical_report(plan) == render_technical_report(plan)
    assert render_business_report(plan) == render_business_report(plan)
