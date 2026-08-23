"""Convert normalized repeated-run traces into deterministic promotion plans.

The classifier deliberately contains no model calls.  It reuses the predictor's
benchmark-neutral call normalization, applies minimum-coverage gates, and emits
evidence suitable for both code-generation workers and human reports.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any, Iterable

from predictor.contracts import FailurePattern
from predictor.features import (
    calls_for,
    common_prefix,
    extract_task_features,
    run_passed,
    skeleton,
    task_id_for,
)

from .contracts import PromotionAction, PromotionCandidate, PromotionEvidence

_INFRASTRUCTURE_TERMINATIONS = {
    "api_error",
    "daily_quota_error",
    "infrastructure_error",
    "model_unavailable",
    "quota_error",
    "rate_limit_error",
    "timeout",
}


def _is_complete(row: dict[str, Any]) -> bool:
    """Accept only explicitly complete, non-infrastructure rows."""

    termination = str(row.get("termination_reason") or "").strip().lower()
    if termination in _INFRASTRUCTURE_TERMINATIONS or any(
        token in termination for token in ("infrastructure", "quota", "rate_limit")
    ):
        return False
    status = row.get("status")
    return str(status).strip().upper() == "COMPLETE"


def _cost_for(row: dict[str, Any]) -> float | None:
    for key in ("cost_usd", "agent_cost", "cost"):
        value = row.get(key)
        if value is None:
            continue
        try:
            cost = float(value)
        except (TypeError, ValueError):
            continue
        if cost >= 0:
            return cost
    return None


def _mean_cost(rows: Iterable[dict[str, Any]]) -> float:
    costs = [cost for row in rows if (cost := _cost_for(row)) is not None]
    return round(statistics.fmean(costs), 6) if costs else 0.0


def _total_cost(rows: Iterable[dict[str, Any]]) -> float:
    return round(sum(cost for row in rows if (cost := _cost_for(row)) is not None), 6)


def _task_sort_key(task_id: str) -> tuple[bool, int | str]:
    return (not task_id.isdigit(), int(task_id) if task_id.isdigit() else task_id)


def _write_name_patterns(
    sequences: list[list[dict[str, Any]]],
) -> tuple[tuple[str, ...], ...]:
    patterns = {
        tuple(call["name"] for call in sequence if call["is_write"])
        for sequence in sequences
    }
    patterns.discard(())
    return tuple(sorted(patterns))


def _safe_read_prefix(sequences: list[list[dict[str, Any]]]) -> tuple[str, ...]:
    prefix = []
    for call in common_prefix(sequences):
        if call["is_write"]:
            break
        prefix.append(call["signature"])
    return tuple(prefix)


def _confidence(
    n: int, min_complete_runs: int, *, signal_strength: float = 1.0
) -> float:
    """Return a bounded evidence score, not a calibrated probability."""

    coverage = min(1.0, n / (2 * min_complete_runs))
    score = signal_strength * (0.65 + 0.35 * coverage)
    return round(max(0.05, min(0.99, score)), 3)


def _candidate_for(
    vertical: str,
    task_id: str,
    rows: list[dict[str, Any]],
    *,
    write_tools: set[str],
    min_complete_runs: int,
) -> PromotionCandidate:
    sequences = [calls_for(row, write_tools) for row in rows]
    passes = sum(run_passed(row) for row in rows)
    n = len(rows)
    pass_rate = passes / n
    passing_sequences = [
        sequence for row, sequence in zip(rows, sequences) if run_passed(row)
    ]
    passing_write_skeletons = {skeleton(sequence) for sequence in passing_sequences}
    nonempty_passing_write_skeletons = {
        item for item in passing_write_skeletons if item
    }
    all_write_skeletons = {skeleton(sequence) for sequence in sequences}
    feature = extract_task_features(
        vertical,
        task_id,
        rows,
        write_tools=write_tools,
        baseline_cost=_mean_cost(rows),
    )
    stable_no_write = (
        passes == n
        and all(not skeleton(sequence) for sequence in sequences)
        and all(sequence == sequences[0] for sequence in sequences[1:])
    )
    stable_read_prefix = (
        feature.longest_common_read_prefix_len > 0 and feature.prefix_ends_before_write
    )
    volatile_write_tail = len(all_write_skeletons) > 1

    if n < min_complete_runs:
        action = PromotionAction.RETAIN
        reason = (
            f"coverage gate not met: {n} complete runs; "
            f"{min_complete_runs} required"
        )
        confidence = round(max(0.05, 0.49 * n / min_complete_runs), 3)
        review_required = True
        next_stage = "COLLECT_MORE_COMPLETE_RUNS"
    elif feature.artifact_flag or feature.ambiguity_signal:
        action = PromotionAction.RETAIN
        reason = "artifact or ambiguity signal prevents automatic promotion"
        confidence = _confidence(n, min_complete_runs, signal_strength=0.6)
        review_required = True
        next_stage = "REVIEW_TRACE_VALIDITY"
    elif pass_rate <= 0.2:
        action = PromotionAction.DROP
        reason = "complete-run pass rate is at or below the 0.20 drop boundary"
        confidence = _confidence(n, min_complete_runs)
        review_required = False
        next_stage = "ARCHIVE_CANDIDATE"
    elif stable_no_write:
        action = PromotionAction.RESPONSE_CRYSTALLIZE
        reason = (
            "all complete runs pass with one stable read/response trace and no writes"
        )
        confidence = _confidence(n, min_complete_runs)
        review_required = False
        next_stage = "GENERATE_RESPONSE_EXECUTOR"
    elif (
        pass_rate >= 0.9
        and len(passing_write_skeletons) == 1
        and len(nonempty_passing_write_skeletons) == 1
    ):
        action = PromotionAction.FULL_CRYSTALLIZE
        reason = "pass rate is at least 0.90 with exactly one passing write skeleton"
        confidence = _confidence(n, min_complete_runs)
        review_required = False
        next_stage = "GENERATE_FULL_EXECUTOR"
    elif stable_read_prefix and volatile_write_tail:
        action = PromotionAction.DECOMPOSE
        reason = "a common read prefix ends at a volatile write-tail boundary"
        confidence = _confidence(n, min_complete_runs, signal_strength=0.9)
        review_required = False
        next_stage = "GENERATE_PREFIX_AND_TAIL_BOUNDARY"
    elif (
        0.2 < pass_rate < 0.9
        and feature.failure_pattern == FailurePattern.AGENT_WANDERED.value
    ):
        action = PromotionAction.LIFT
        reason = "mid-band pass rate reflects a bounded genuine action inconsistency"
        confidence = _confidence(n, min_complete_runs, signal_strength=0.85)
        review_required = False
        next_stage = "RUN_LIFTING_EXPERIMENT"
    else:
        action = PromotionAction.RETAIN
        reason = "trace evidence does not cross an automatic treatment boundary"
        confidence = _confidence(n, min_complete_runs, signal_strength=0.55)
        review_required = True
        next_stage = "HUMAN_REVIEW"

    evidence = PromotionEvidence(
        n=n,
        passes=passes,
        pass_rate=round(pass_rate, 6),
        mean_cost_usd=_mean_cost(rows),
        write_name_patterns=_write_name_patterns(sequences),
        read_prefix=_safe_read_prefix(sequences),
        reason=reason,
        confidence=confidence,
        review_required=review_required,
        proposed_next_stage=next_stage,
    )
    return PromotionCandidate(
        vertical=vertical,
        task_id=task_id,
        action=action,
        evidence=evidence,
    )


def build_promotion_plan(
    vertical: str,
    rows: list[dict[str, Any]],
    *,
    write_tools: set[str],
    min_complete_runs: int = 5,
) -> dict[str, Any]:
    """Build a JSON-serializable, deterministically ordered promotion plan."""

    if not vertical:
        raise ValueError("vertical must be non-empty")
    if min_complete_runs < 1:
        raise ValueError("min_complete_runs must be at least 1")

    complete_rows = [row for row in rows if _is_complete(row)]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in complete_rows:
        grouped[task_id_for(row)].append(row)

    candidates = [
        _candidate_for(
            vertical,
            task_id,
            grouped[task_id],
            write_tools=write_tools,
            min_complete_runs=min_complete_runs,
        )
        for task_id in sorted(grouped, key=_task_sort_key)
    ]
    counts = Counter(candidate.action.value for candidate in candidates)
    action_counts = {
        action.value: counts.get(action.value, 0) for action in PromotionAction
    }
    return {
        "schema_version": 1,
        "vertical": vertical,
        "summary": {
            "input_rows": len(rows),
            "complete_rows": len(complete_rows),
            "ignored_rows": len(rows) - len(complete_rows),
            "task_count": len(candidates),
            "min_complete_runs": min_complete_runs,
            "promote_pass_rate": 0.9,
            "drop_pass_rate": 0.2,
            "action_counts": action_counts,
            "observed_cost_usd": _total_cost(complete_rows),
            "mean_complete_cost_usd": _mean_cost(complete_rows),
        },
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
