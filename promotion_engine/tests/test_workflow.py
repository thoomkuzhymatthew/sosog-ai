from promotion_engine.workflow import build_coding_jobs, enrich_plan


def _candidate(task_id: str, action: str, cost: float) -> dict:
    return {
        "vertical": "airline",
        "task_id": task_id,
        "action": action,
        "actual_n": 7,
        "pass_rate": 1.0,
        "mean_cost_usd": cost,
        "confidence": 0.95,
        "reason": "stable evidence",
        "write_name_patterns": {"cancel_reservation": 7},
    }


def _nested_candidate(task_id: str, action: str, cost: float) -> dict:
    return {
        "vertical": "airline",
        "task_id": task_id,
        "action": action,
        "evidence": {
            "n": 7,
            "pass_rate": 1.0,
            "mean_cost_usd": cost,
            "confidence": 0.95,
            "reason": "stable nested evidence",
            "write_name_patterns": [["cancel_reservation"]],
        },
    }


def test_enrich_plan_places_parser_after_classification_and_before_gates():
    result = enrich_plan(
        {
            "vertical": "airline",
            "summary": {},
            "candidates": [_candidate("19", "FULL_CRYSTALLIZE", 0.1)],
        }
    )

    design = result["candidates"][0]["execution_design"]
    assert design["nl_parser_placement"] == "before_schema_and_consistency_gates"
    assert design["runtime_path"].index("cheap_structured_intent_parser") < design[
        "runtime_path"
    ].index("schema_gate")
    assert "HUMAN_SAFETY_REVIEW" in result["workflow"]["stages"]


def test_lift_does_not_get_a_cheap_parser_prematurely():
    result = enrich_plan(
        {
            "vertical": "airline",
            "summary": {},
            "candidates": [_candidate("8", "LIFT", 0.2)],
        }
    )
    design = result["candidates"][0]["execution_design"]
    assert design["nl_parser_placement"] == "none_until_lifted_task_reclassifies"
    assert "full_agent_with_exemplars" in design["runtime_path"]


def test_jobs_are_bounded_ranked_and_never_authorize_deploy():
    plan = enrich_plan(
        {
            "vertical": "airline",
            "summary": {},
            "candidates": [
                _candidate("19", "FULL_CRYSTALLIZE", 0.1),
                _candidate("44", "DROP", 0.4),
                _candidate("0", "RETAIN", 0.8),
            ],
        }
    )
    jobs = build_coding_jobs(plan, repository="/opt/sosog/repo", max_jobs=1)
    assert len(jobs) == 1
    assert jobs[0]["task_id"] == "19"
    assert jobs[0]["may_merge_or_deploy"] is False
    assert jobs[0]["trace_contract"]["immutable"] is True
    assert "agent_events" in jobs[0]["trace_contract"]["required"]
    assert "Do not merge, deploy" in jobs[0]["prompt"]


def test_jobs_accept_nested_classifier_evidence():
    plan = enrich_plan(
        {
            "vertical": "airline",
            "summary": {},
            "candidates": [
                _nested_candidate("12", "FULL_CRYSTALLIZE", 0.2),
                _nested_candidate("19", "FULL_CRYSTALLIZE", 0.1),
            ],
        }
    )
    jobs = build_coding_jobs(plan, repository="/opt/sosog/repo", max_jobs=1)
    assert jobs[0]["task_id"] == "12"
    assert "N=7" in jobs[0]["prompt"]
    assert "stable nested evidence" in jobs[0]["prompt"]
