"""Turn promotion classifications into bounded coding-agent work items.

The trace classifier decides *what kind* of intervention deserves testing.
This module decides where natural-language interpretation belongs and emits a
reviewable specification for the coding worker.  It deliberately never runs a
coding agent or promotes generated code by itself.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

ACTION_DESIGNS: dict[str, dict[str, Any]] = {
    "FULL_CRYSTALLIZE": {
        "nl_parser_placement": "before_schema_and_consistency_gates",
        "runtime_path": [
            "raw_request",
            "cheap_structured_intent_parser",
            "schema_gate",
            "consistency_gate",
            "deterministic_executor",
            "programmatic_verifier",
        ],
        "fallback": "full_agent_on_parse_ambiguity_or_gate_deferral",
        "coding_job": "generate_executor_and_gates",
    },
    "RESPONSE_CRYSTALLIZE": {
        "nl_parser_placement": "before_policy_response_template",
        "runtime_path": [
            "raw_request",
            "cheap_intent_parser",
            "policy_and_state_gate",
            "deterministic_response_template",
            "communication_verifier",
        ],
        "fallback": "full_agent_unless_policy_response_is_proven",
        "coding_job": "generate_response_template_and_gate",
    },
    "DECOMPOSE": {
        "nl_parser_placement": "not_in_the_volatile_tail",
        "runtime_path": [
            "raw_request",
            "deterministic_read_only_prefix",
            "validated_handoff",
            "full_agent_tail",
            "programmatic_verifier",
        ],
        "fallback": "full_agent_from_start_on_prefix_or_handoff_failure",
        "coding_job": "generate_read_prefix_and_handoff",
    },
    "LIFT": {
        "nl_parser_placement": "none_until_lifted_task_reclassifies",
        "runtime_path": [
            "raw_request",
            "trace_exemplar_selection",
            "full_agent_with_exemplars",
            "programmatic_verifier",
            "reclassify_after_matched_ab",
        ],
        "fallback": "unlifted_full_agent",
        "coding_job": "generate_lifting_experiment",
    },
    "RETAIN": {
        "nl_parser_placement": "none",
        "runtime_path": ["raw_request", "full_agent"],
        "fallback": "existing_agent_path",
        "coding_job": None,
    },
    "DROP": {
        "nl_parser_placement": "none",
        "runtime_path": ["raw_request", "early_reject_or_escalate"],
        "fallback": "human_or_alternative_strategy",
        "coding_job": "generate_early_exit_policy",
    },
}


_ACTION_PRIORITY = {
    "FULL_CRYSTALLIZE": 0,
    "RESPONSE_CRYSTALLIZE": 1,
    "DECOMPOSE": 2,
    "LIFT": 3,
    "DROP": 4,
}


def _evidence(candidate: dict[str, Any], name: str, default: Any = None) -> Any:
    """Read the classifier's nested evidence while accepting legacy flat plans."""

    if name in candidate:
        return candidate[name]
    evidence = candidate.get("evidence")
    if isinstance(evidence, dict):
        return evidence.get(name, default)
    return default


def enrich_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Attach runtime and coding-stage designs without changing evidence."""

    result = deepcopy(plan)
    for candidate in result.get("candidates", []):
        action = str(candidate["action"])
        if action not in ACTION_DESIGNS:
            raise ValueError(f"unsupported promotion action: {action}")
        candidate["execution_design"] = deepcopy(ACTION_DESIGNS[action])
        candidate["promotion_review_required"] = True
    result["workflow"] = {
        "schema_version": 1,
        "stages": [
            "INGEST",
            "CLASSIFY",
            "GENERATE_CHANGE",
            "VERIFY_HELD_OUT",
            "HUMAN_SAFETY_REVIEW",
            "PROPOSE_PR",
            "SHADOW_MEASURE",
            "REPORT",
        ],
        "promotion_rule": (
            "coding agents may propose code; only deterministic held-out checks "
            "and the configured human safety review may advance it"
        ),
        "observability_rule": (
            "every coding-agent attempt emits an immutable JSONL event trace and "
            "a terminal outcome record, including failed attempts"
        ),
    }
    return result


def coding_job_prompt(candidate: dict[str, Any], *, repository: str) -> str:
    """Render a bounded prompt for one isolated Codex worktree."""

    action = str(candidate["action"])
    design = candidate.get("execution_design") or ACTION_DESIGNS.get(action)
    if design is None or design.get("coding_job") is None:
        raise ValueError(f"candidate action {action} has no coding job")

    task_id = str(candidate["task_id"])
    patterns = _evidence(candidate, "write_name_patterns", [])
    return (
        f"You are the coding worker for SOSOG candidate {task_id}.\n"
        f"Repository: {repository}\n"
        f"Classification: {action}\n"
        f"Job type: {design['coding_job']}\n"
        f"Evidence: N={_evidence(candidate, 'n', _evidence(candidate, 'actual_n', 0))}, "
        f"pass_rate={_evidence(candidate, 'pass_rate', 0)}, "
        f"mean_observed_cost_usd={_evidence(candidate, 'mean_cost_usd', 0)}.\n"
        f"Observed write-name patterns: {patterns}.\n"
        f"Classifier reason: {_evidence(candidate, 'reason', 'not supplied')}\n"
        f"Required runtime path: {' -> '.join(design['runtime_path'])}.\n"
        f"Required fallback: {design['fallback']}.\n\n"
        "Work only in your assigned worktree. First locate the exact traces, tool "
        "contracts, task definitions, and programmatic verifier. Generate the "
        "smallest parameterized change appropriate to the classification. Never "
        "hard-code task-instance identifiers as a claimed family solution. Add "
        "schema and pre-write consistency gates; a deferral must execute no write. "
        "Add held-out and adversarial tests, record model calls/tokens/cost, and "
        "write a concise evidence note. Do not merge, deploy, or modify production "
        "credentials. Finish by reporting changed files, tests, measured evidence, "
        "and unresolved human safety-review questions."
    )


def build_coding_jobs(
    plan: dict[str, Any],
    *,
    repository: str,
    max_jobs: int = 3,
) -> list[dict[str, Any]]:
    """Select the highest-value runnable candidates for parallel workers."""

    if max_jobs < 1:
        raise ValueError("max_jobs must be at least one")
    candidates = [
        candidate
        for candidate in plan.get("candidates", [])
        if (
            candidate.get("execution_design")
            or ACTION_DESIGNS.get(str(candidate.get("action")), {})
        ).get("coding_job")
        is not None
    ]
    candidates.sort(
        key=lambda item: (
            _ACTION_PRIORITY.get(str(item.get("action")), 99),
            -float(_evidence(item, "mean_cost_usd", 0) or 0),
            -float(_evidence(item, "confidence", 0) or 0),
            str(item.get("task_id")),
        )
    )
    jobs = []
    for candidate in candidates[:max_jobs]:
        task_id = str(candidate["task_id"])
        action = str(candidate["action"])
        jobs.append(
            {
                "job_id": f"{candidate.get('vertical', plan.get('vertical', 'unknown'))}-{task_id}-{action.lower()}",
                "task_id": task_id,
                "action": action,
                "prompt": coding_job_prompt(candidate, repository=repository),
                "requires_human_safety_review": True,
                "may_merge_or_deploy": False,
                "trace_contract": {
                    "schema_version": 1,
                    "format": "jsonl",
                    "immutable": True,
                    "required": [
                        "job_id",
                        "prompt_sha256",
                        "started_at",
                        "finished_at",
                        "duration_seconds",
                        "agent_events",
                        "exit_status",
                        "git_diff_stat",
                        "test_evidence",
                        "review_decision",
                    ],
                    "when_exposed_by_runtime": [
                        "model",
                        "input_tokens",
                        "cached_input_tokens",
                        "output_tokens",
                        "cost_usd",
                    ],
                },
            }
        )
    return jobs
