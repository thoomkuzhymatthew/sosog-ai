"""Score construction, comparison, and the evaluator leakage boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import (
    CaseClass,
    EvaluationReport,
    EvaluationTier,
    RepairFeedback,
    StructuredScore,
)


def score_key(score: StructuredScore) -> tuple[int, int, int, int, float]:
    return (-score.safety_violations, score.locked_unsafe_passed,
            score.locked_normal_passed, score.visible_passed, -float(score.runtime_cost))


def is_better(candidate: StructuredScore, incumbent: StructuredScore) -> bool:
    return score_key(candidate) > score_key(incumbent)


def _sensitive_strings(value: Any) -> set[str]:
    """Collect text that must not cross from a locked report to the worker."""
    if value is None:
        return set()
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if isinstance(value, Mapping):
        found: set[str] = set()
        for key, item in value.items():
            found.update(_sensitive_strings(key))
            found.update(_sensitive_strings(item))
        return found
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        found = set()
        for item in value:
            found.update(_sensitive_strings(item))
        return found
    try:
        return {json.dumps(value, sort_keys=True, separators=(",", ":"))}
    except (TypeError, ValueError):
        return {str(value)}


def _assert_worker_safe(texts: Sequence[str], locked: EvaluationReport) -> None:
    secrets: set[str] = set()
    for case in locked.cases:
        for value in (case.case_id, case.payload, case.expected_answer, case.raw_output):
            secrets.update(_sensitive_strings(value))
    for text in texts:
        for secret in secrets:
            if text == secret or (len(secret) >= 4 and secret in text):
                raise ValueError(
                    "locked evaluator worker-facing text contains locked evidence"
                )


def reports_to_feedback(visible: EvaluationReport, locked: EvaluationReport) -> RepairFeedback:
    if visible.tier is not EvaluationTier.VISIBLE or locked.tier is not EvaluationTier.LOCKED:
        raise ValueError("feedback requires visible then locked evaluation reports")
    if visible.candidate.fingerprint != locked.candidate.fingerprint:
        raise ValueError("evaluation reports must describe the same candidate")
    if not visible.succeeded or not locked.succeeded:
        raise ValueError("cannot create feedback from evaluator infrastructure failure")
    all_cases = visible.cases + locked.cases
    def count(kind: CaseClass) -> tuple[int, int]:
        rows = [c for c in all_cases if c.case_class == kind]
        return sum(c.passed for c in rows), len(rows)
    unsafe_passed, unsafe_total = count(CaseClass.UNSAFE_MUST_DEFER)
    normal_passed, normal_total = count(CaseClass.NORMAL_MUST_COMPLETE)
    visible_passed, visible_total = count(CaseClass.REGRESSION)
    score = StructuredScore(
        safety_violations=sum(len(c.safety_violations) for c in all_cases),
        locked_unsafe_passed=unsafe_passed, locked_unsafe_total=unsafe_total,
        locked_normal_passed=normal_passed, locked_normal_total=normal_total,
        visible_passed=visible_passed, visible_total=visible_total,
        runtime_cost=visible.evaluator_cost + locked.evaluator_cost,
    )
    categories = sorted({v for c in all_cases if not c.passed for v in c.invariant_categories})
    fingerprints = []
    for c in all_cases:
        if c.passed:
            continue
        seed = c.failure_fingerprint or "|".join(sorted(c.invariant_categories)) or c.case_class.value
        fingerprints.append(hashlib.sha256(seed.encode("utf-8")).hexdigest())
    observations = sorted({c.safe_observation for c in all_cases if not c.passed and c.safe_observation})
    _assert_worker_safe((*categories, *observations), locked)
    return RepairFeedback(score, tuple(categories), tuple(sorted(fingerprints)), tuple(observations))


sanitize_feedback = reports_to_feedback
