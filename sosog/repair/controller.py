"""Deterministic bounded search over injected evaluator and worker interfaces."""

from __future__ import annotations

import time
from collections.abc import Callable

from .contracts import (AttemptRecord, AttemptStatus, CandidateReference,
                        ControllerPolicy, EvaluationReport, EvaluationTier,
                        RepairLoopResult, RepairWorkerResult, StopReason,
                        StructuredScore)
from .evaluator import is_better, reports_to_feedback
from .vertical_adapter import LockedEvaluator, RepairWorker


Recorder = Callable[[AttemptRecord], None]


def _no_evidence_score() -> StructuredScore:
    """Represent a terminal run that never obtained evaluator evidence."""
    return StructuredScore(0, 0, 0, 0, 0, 0, 0)


def _has_repeated_cycle(values: list[str], window: int) -> bool:
    """Return true for a repeated suffix cycle of at least two states."""
    recent = values[-window:]
    for cycle_size in range(2, len(recent) // 2 + 1):
        if recent[-cycle_size:] == recent[-2 * cycle_size:-cycle_size]:
            return True
    return False


def _result(best: CandidateReference, score: StructuredScore,
            records: list[AttemptRecord], reason: StopReason, total_cost: float) -> RepairLoopResult:
    feedback = next((r for r in reversed(records) if r.accepted and r.feedback_fingerprint), None)
    categories: tuple[str, ...] = ()
    if feedback:
        # Re-sanitize the accepted audit reports; raw evidence stays inside records.
        successful = [r for r in feedback.reports if r.succeeded]
        if len(successful) == 2:
            categories = reports_to_feedback(successful[0], successful[1]).invariant_categories
    action = ("Perform independent human safety review; do not merge or deploy."
              if reason == StopReason.PENDING_HUMAN_SAFETY_REVIEW
              else "Review the recorded evidence and decide whether to revise policy, cases, or proposal.")
    return RepairLoopResult(best, score, tuple(records), reason, categories, action, total_cost)


def run_repair_loop(
    initial_candidate: CandidateReference,
    evaluator: LockedEvaluator,
    worker: RepairWorker,
    policy: ControllerPolicy = ControllerPolicy(),
    *,
    recorder: Recorder | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> RepairLoopResult:
    """Evaluate and repair candidates without ever handing locked reports to a worker."""
    started = clock()
    records: list[AttemptRecord] = []
    seen_candidates: list[str] = []
    seen_feedback: list[str] = []
    total_cost = 0.0
    evaluator_failures = 0
    stagnant = 0
    unsafe_tradeoffs = 0
    pending_worker_cost = 0.0
    best = initial_candidate
    best_score: StructuredScore | None = None
    best_feedback = None

    def record(value: AttemptRecord) -> None:
        records.append(value)
        if recorder:
            recorder(value)

    try:
        manifests = {
            tier: evaluator.suite_manifest(tier)
            for tier in (EvaluationTier.VISIBLE, EvaluationTier.LOCKED)
        }
        if any(manifest.tier is not tier for tier, manifest in manifests.items()):
            raise ValueError("evaluator returned a manifest for the wrong tier")
    except Exception as exc:
        record(AttemptRecord(
            0, initial_candidate, None, None, False, 0.0,
            AttemptStatus.EVALUATOR_FAILURE,
            detail=f"manifest {type(exc).__name__}: {exc}",
        ))
        return _result(
            initial_candidate, _no_evidence_score(), records,
            StopReason.EVALUATOR_BLOCKED, total_cost,
        )

    candidate = initial_candidate
    for attempt in range(policy.max_attempts + 1):
        attempt_cost = pending_worker_cost
        pending_worker_cost = 0.0
        if clock() - started >= policy.max_seconds:
            return _result(best, best_score or _no_evidence_score(), records,
                           StopReason.TIME_LIMIT, total_cost)
        if attempt and total_cost >= policy.max_cost:
            return _result(best, best_score, records, StopReason.COST_LIMIT, total_cost)  # type: ignore[arg-type]

        reports: list[EvaluationReport] = []
        try:
            for tier in (EvaluationTier.VISIBLE, EvaluationTier.LOCKED):
                report = evaluator.evaluate(candidate, tier)
                if report.candidate.fingerprint != candidate.fingerprint or report.tier != tier:
                    raise RuntimeError("evaluator returned mismatched candidate or tier")
                if not manifests[tier].matches(report):
                    raise RuntimeError(
                        "evaluator report does not match the frozen suite manifest"
                    )
                reports.append(report)
                total_cost += report.evaluator_cost
                attempt_cost += report.evaluator_cost
                if not report.succeeded:
                    raise RuntimeError(report.infrastructure_error)
            feedback = reports_to_feedback(reports[0], reports[1])
        except Exception as exc:
            evaluator_failures += 1
            rec = AttemptRecord(
                attempt, candidate, None, None, False, attempt_cost,
                AttemptStatus.EVALUATOR_FAILURE, tuple(reports),
                f"{type(exc).__name__}: {exc}",
            )
            record(rec)
            if evaluator_failures >= policy.max_evaluator_failures:
                if best_score is None:
                    # A terminal result requires evidence for a best candidate; this score
                    # explicitly represents absence of automated evidence.
                    best_score = _no_evidence_score()
                return _result(best, best_score, records, StopReason.EVALUATOR_BLOCKED, total_cost)
            if attempt >= policy.max_attempts:
                return _result(best, best_score or _no_evidence_score(), records,
                               StopReason.ATTEMPT_LIMIT, total_cost)
            if total_cost >= policy.max_cost:
                return _result(best, best_score or _no_evidence_score(), records,
                               StopReason.COST_LIMIT, total_cost)
            if clock() - started >= policy.max_seconds:
                return _result(best, best_score or _no_evidence_score(), records,
                               StopReason.TIME_LIMIT, total_cost)
            continue

        evaluator_failures = 0
        score = feedback.score
        accepted = best_score is None or is_better(score, best_score)
        safety_regression = best_score is not None and score.safety_violations > best_score.safety_violations
        ordinary_better = best_score is not None and (
            score.locked_unsafe_passed, score.locked_normal_passed, score.visible_passed
        ) > (best_score.locked_unsafe_passed, best_score.locked_normal_passed, best_score.visible_passed)
        if safety_regression and ordinary_better:
            unsafe_tradeoffs += 1
        else:
            unsafe_tradeoffs = 0
        if accepted:
            best, best_score, best_feedback = candidate, score, feedback
            stagnant = 0
        else:
            stagnant += 1
        rec = AttemptRecord(attempt, candidate, score, feedback.fingerprint, accepted,
                            attempt_cost,
                            AttemptStatus.ACCEPTED if accepted else AttemptStatus.REJECTED,
                            tuple(reports))
        record(rec)

        if safety_regression and policy.stop_on_safety_regression:
            return _result(best, best_score, records, StopReason.REGRESSED_SAFETY, total_cost)
        if unsafe_tradeoffs >= policy.no_safe_improvement_window:
            return _result(best, best_score, records, StopReason.NO_SAFE_IMPROVEMENT, total_cost)
        if total_cost >= policy.max_cost:
            return _result(best, best_score, records, StopReason.COST_LIMIT, total_cost)
        if clock() - started >= policy.max_seconds:
            return _result(best, best_score, records, StopReason.TIME_LIMIT, total_cost)
        if score.perfect and accepted:
            return _result(best, best_score, records, StopReason.PENDING_HUMAN_SAFETY_REVIEW, total_cost)
        if attempt >= policy.max_attempts:
            return _result(best, best_score, records, StopReason.ATTEMPT_LIMIT, total_cost)
        if stagnant >= policy.stagnation_window:
            return _result(best, best_score, records, StopReason.STAGNATED, total_cost)

        seen_candidates.append(candidate.fingerprint)
        seen_feedback.append(feedback.fingerprint)
        # Stop before invoking another worker once distinct candidates have
        # reproduced a failure cycle. The worker sees no extra feedback call.
        if _has_repeated_cycle(seen_feedback, policy.oscillation_window):
            return _result(best, best_score, records, StopReason.OSCILLATING, total_cost)
        # Only the sanitized object is passed across the worker boundary.
        try:
            proposal = worker.repair(best, best_feedback)
            worker_cost = proposal.cost if isinstance(proposal, RepairWorkerResult) else 0.0
            candidate = proposal.candidate if isinstance(proposal, RepairWorkerResult) else proposal
            if not isinstance(candidate, CandidateReference):
                raise TypeError(
                    "repair worker must return CandidateReference or RepairWorkerResult"
                )
        except Exception as exc:
            record(AttemptRecord(
                attempt + 1, None, None, None, False, 0.0,
                AttemptStatus.WORKER_FAILURE, detail=f"{type(exc).__name__}: {exc}",
            ))
            return _result(
                best, best_score, records, StopReason.WORKER_BLOCKED, total_cost
            )
        total_cost += worker_cost
        pending_worker_cost = worker_cost
        if total_cost >= policy.max_cost:
            record(AttemptRecord(
                attempt + 1, candidate, None, None, False, worker_cost,
                AttemptStatus.COST_LIMIT,
            ))
            return _result(best, best_score, records, StopReason.COST_LIMIT, total_cost)
        if clock() - started >= policy.max_seconds:
            record(AttemptRecord(
                attempt + 1, candidate, None, None, False, worker_cost,
                AttemptStatus.TIME_LIMIT,
            ))
            return _result(best, best_score, records, StopReason.TIME_LIMIT, total_cost)
        if candidate.fingerprint == seen_candidates[-1]:
            record(AttemptRecord(attempt + 1, candidate, None, None, False, worker_cost,
                                 AttemptStatus.DUPLICATE_CANDIDATE))
            return _result(best, best_score, records, StopReason.DUPLICATE_CANDIDATE, total_cost)
        if candidate.fingerprint in seen_candidates:
            record(AttemptRecord(attempt + 1, candidate, None, None, False, worker_cost,
                                 AttemptStatus.OSCILLATING_CANDIDATE))
            return _result(best, best_score, records, StopReason.OSCILLATING, total_cost)

    return _result(best, best_score or _no_evidence_score(), records,
                   StopReason.ATTEMPT_LIMIT, total_cost)
