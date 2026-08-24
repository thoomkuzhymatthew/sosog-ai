"""Validated, JSON-safe contracts for the bounded repair loop."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


def _digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _json_safe(value: object) -> None:
    try:
        json.dumps(value, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be JSON-serializable") from exc


class EvaluationTier(StrEnum):
    VISIBLE = "VISIBLE"
    LOCKED = "LOCKED"


class CaseClass(StrEnum):
    REGRESSION = "REGRESSION"
    NORMAL_MUST_COMPLETE = "NORMAL_MUST_COMPLETE"
    UNSAFE_MUST_DEFER = "UNSAFE_MUST_DEFER"


@dataclass(frozen=True)
class SuiteManifest:
    """Payload-free identity and shape of one immutable evaluation suite."""

    digest: str
    tier: EvaluationTier
    case_counts: Mapping[CaseClass, int]

    def __post_init__(self) -> None:
        if (not isinstance(self.digest, str) or len(self.digest) != 64
                or any(c not in "0123456789abcdef" for c in self.digest.lower())):
            raise ValueError("suite digest must be a SHA-256 hex digest")
        object.__setattr__(self, "digest", self.digest.lower())
        if not isinstance(self.tier, EvaluationTier):
            raise ValueError("suite tier must be an EvaluationTier")
        try:
            counts = dict(self.case_counts)
        except (TypeError, ValueError) as exc:
            raise ValueError("suite case_counts must be a mapping") from exc
        if any(
            not isinstance(kind, CaseClass) or type(count) is not int or count < 0
            for kind, count in counts.items()
        ):
            raise ValueError("suite counts require CaseClass keys and non-negative integers")
        expected = (
            {CaseClass.REGRESSION}
            if self.tier is EvaluationTier.VISIBLE
            else {CaseClass.NORMAL_MUST_COMPLETE, CaseClass.UNSAFE_MUST_DEFER}
        )
        if set(counts) != expected or any(counts[kind] <= 0 for kind in expected):
            raise ValueError("suite manifest must contain positive counts for its tier")
        object.__setattr__(self, "case_counts", MappingProxyType(counts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "tier": self.tier.value,
            "case_counts": {
                kind.value: self.case_counts[kind]
                for kind in sorted(self.case_counts, key=lambda item: item.value)
            },
        }

    def matches(self, report: "EvaluationReport") -> bool:
        counts = {
            kind: sum(case.case_class is kind for case in report.cases)
            for kind in self.case_counts
        }
        return (
            report.tier is self.tier
            and report.suite_digest == self.digest
            and counts == self.case_counts
        )


class StopReason(StrEnum):
    STAGNATED = "STAGNATED"
    DUPLICATE_CANDIDATE = "DUPLICATE_CANDIDATE"
    OSCILLATING = "OSCILLATING"
    REGRESSED_SAFETY = "REGRESSED_SAFETY"
    ATTEMPT_LIMIT = "ATTEMPT_LIMIT"
    COST_LIMIT = "COST_LIMIT"
    TIME_LIMIT = "TIME_LIMIT"
    EVALUATOR_BLOCKED = "EVALUATOR_BLOCKED"
    WORKER_BLOCKED = "WORKER_BLOCKED"
    NO_SAFE_IMPROVEMENT = "NO_SAFE_IMPROVEMENT"
    PENDING_HUMAN_SAFETY_REVIEW = "PENDING_HUMAN_SAFETY_REVIEW"


@dataclass(frozen=True)
class CandidateReference:
    digest: str
    location: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (not isinstance(self.digest, str) or len(self.digest) != 64
                or any(c not in "0123456789abcdef" for c in self.digest.lower())):
            raise ValueError("candidate digest must be a 64-character SHA-256 hex digest")
        object.__setattr__(self, "digest", self.digest.lower())
        if self.location is not None and (
            not isinstance(self.location, str) or not self.location.strip()
        ):
            raise ValueError("candidate location must be a non-empty string")
        _json_safe(dict(self.metadata))

    @classmethod
    def from_content(cls, content: bytes | str, **kwargs: Any) -> "CandidateReference":
        if not isinstance(content, (bytes, str)):
            raise ValueError("candidate content must be bytes or text")
        raw = content.encode("utf-8") if isinstance(content, str) else content
        return cls(hashlib.sha256(raw).hexdigest(), **kwargs)

    @property
    def fingerprint(self) -> str:
        return self.digest.lower()

    def to_dict(self) -> dict[str, Any]:
        return {"digest": self.digest, "location": self.location, "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class RepairWorkerResult:
    """A worker proposal plus all model/worker/infrastructure cost it incurred."""
    candidate: CandidateReference
    cost: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, CandidateReference):
            raise ValueError("worker candidate must be a CandidateReference")
        if (isinstance(self.cost, bool) or not isinstance(self.cost, (int, float))
                or self.cost < 0 or not math.isfinite(self.cost)):
            raise ValueError("worker cost must be finite and non-negative")


@dataclass(frozen=True)
class CaseEvaluation:
    case_class: CaseClass
    passed: bool
    safety_violations: tuple[str, ...] = ()
    invariant_categories: tuple[str, ...] = ()
    failure_fingerprint: str | None = None
    safe_observation: str | None = None
    # Audit-only fields. These are deliberately absent from RepairFeedback.
    case_id: str | None = None
    payload: Any = None
    expected_answer: Any = None
    raw_output: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.case_class, CaseClass):
            raise ValueError("case_class must be a CaseClass")
        if type(self.passed) is not bool:
            raise ValueError("passed must be a boolean")
        if self.passed and (self.safety_violations or self.failure_fingerprint):
            raise ValueError("a passing case cannot carry failure evidence")
        for values in (self.safety_violations, self.invariant_categories):
            if any(not isinstance(v, str) or not v for v in values):
                raise ValueError("categories must be non-empty strings")
        for value, name in (
            (self.failure_fingerprint, "failure_fingerprint"),
            (self.safe_observation, "safe_observation"),
            (self.case_id, "case_id"),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string when supplied")
        _json_safe(asdict(self))


@dataclass(frozen=True)
class StructuredScore:
    safety_violations: int
    locked_unsafe_passed: int
    locked_unsafe_total: int
    locked_normal_passed: int
    locked_normal_total: int
    visible_passed: int
    visible_total: int
    runtime_cost: float = 0.0

    def __post_init__(self) -> None:
        values = (self.safety_violations, self.locked_unsafe_passed,
                  self.locked_unsafe_total, self.locked_normal_passed,
                  self.locked_normal_total, self.visible_passed, self.visible_total)
        if any(type(v) is not int or v < 0 for v in values):
            raise ValueError("score counts must be non-negative integers")
        if self.locked_unsafe_passed > self.locked_unsafe_total or self.locked_normal_passed > self.locked_normal_total or self.visible_passed > self.visible_total:
            raise ValueError("passed count cannot exceed total")
        if (isinstance(self.runtime_cost, bool)
                or not isinstance(self.runtime_cost, (int, float))
                or self.runtime_cost < 0 or not math.isfinite(self.runtime_cost)):
            raise ValueError("runtime cost must be finite and non-negative")

    @property
    def perfect(self) -> bool:
        # Empty suites are absence of evidence, never evidence of perfection.
        return (self.locked_unsafe_total > 0 and self.locked_normal_total > 0
                and self.visible_total > 0 and self.safety_violations == 0
                and self.locked_unsafe_passed == self.locked_unsafe_total
                and self.locked_normal_passed == self.locked_normal_total
                and self.visible_passed == self.visible_total)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvaluationReport:
    candidate: CandidateReference
    tier: EvaluationTier
    cases: tuple[CaseEvaluation, ...]
    infrastructure_error: str | None = None
    evaluator_cost: float = 0.0
    suite_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, CandidateReference):
            raise ValueError("candidate must be a CandidateReference")
        if not isinstance(self.tier, EvaluationTier):
            raise ValueError("tier must be an EvaluationTier")
        if not isinstance(self.cases, tuple) or any(
            not isinstance(case, CaseEvaluation) for case in self.cases
        ):
            raise ValueError("cases must be a tuple of CaseEvaluation values")
        if self.infrastructure_error is not None and (
            not isinstance(self.infrastructure_error, str)
            or not self.infrastructure_error.strip()
        ):
            raise ValueError("infrastructure_error must be non-empty when supplied")
        if self.infrastructure_error is not None and self.cases:
            raise ValueError("infrastructure failure cannot contain case results")
        if self.succeeded:
            if (not isinstance(self.suite_digest, str)
                    or len(self.suite_digest) != 64
                    or any(c not in "0123456789abcdef" for c in self.suite_digest.lower())):
                raise ValueError("successful evaluation requires a suite SHA-256 digest")
            object.__setattr__(self, "suite_digest", self.suite_digest.lower())
            allowed = ({CaseClass.REGRESSION} if self.tier == EvaluationTier.VISIBLE
                       else {CaseClass.NORMAL_MUST_COMPLETE, CaseClass.UNSAFE_MUST_DEFER})
            if any(case.case_class not in allowed for case in self.cases):
                raise ValueError("case class does not belong to evaluation tier")
        if (isinstance(self.evaluator_cost, bool)
                or not isinstance(self.evaluator_cost, (int, float))
                or self.evaluator_cost < 0 or not math.isfinite(self.evaluator_cost)):
            raise ValueError("evaluator cost must be finite and non-negative")

    @property
    def succeeded(self) -> bool:
        return self.infrastructure_error is None

    def to_dict(self) -> dict[str, Any]:
        return {"candidate": self.candidate.to_dict(), "tier": self.tier.value,
                "cases": [asdict(c) for c in self.cases], "infrastructure_error": self.infrastructure_error,
                "evaluator_cost": self.evaluator_cost, "suite_digest": self.suite_digest}


@dataclass(frozen=True)
class RepairFeedback:
    score: StructuredScore
    invariant_categories: tuple[str, ...]
    failure_fingerprints: tuple[str, ...]
    safe_observations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.score, StructuredScore):
            raise ValueError("feedback score must be a StructuredScore")
        for values in (self.invariant_categories, self.failure_fingerprints, self.safe_observations):
            if not isinstance(values, tuple):
                raise ValueError("feedback collections must be tuples")
            if any(not isinstance(v, str) or not v for v in values):
                raise ValueError("feedback entries must be non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score.to_dict(), "invariant_categories": list(self.invariant_categories),
                "failure_fingerprints": list(self.failure_fingerprints), "safe_observations": list(self.safe_observations),
                "fingerprint": self.fingerprint}

    @property
    def fingerprint(self) -> str:
        value = {"score": self.score.to_dict(), "invariant_categories": sorted(set(self.invariant_categories)),
                 "failure_fingerprints": sorted(set(self.failure_fingerprints)),
                 "safe_observations": sorted(set(self.safe_observations))}
        return _digest(value)


class AttemptStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EVALUATOR_FAILURE = "EVALUATOR_FAILURE"
    WORKER_FAILURE = "WORKER_FAILURE"
    DUPLICATE_CANDIDATE = "DUPLICATE_CANDIDATE"
    OSCILLATING_CANDIDATE = "OSCILLATING_CANDIDATE"
    COST_LIMIT = "COST_LIMIT"
    TIME_LIMIT = "TIME_LIMIT"


@dataclass(frozen=True)
class AttemptRecord:
    attempt: int
    candidate: CandidateReference | None
    score: StructuredScore | None
    feedback_fingerprint: str | None
    accepted: bool
    cost: float
    status: AttemptStatus
    reports: tuple[EvaluationReport, ...] = ()
    detail: str | None = None

    def __post_init__(self) -> None:
        if type(self.attempt) is not int or self.attempt < 0:
            raise ValueError("attempt must be a non-negative integer")
        if (isinstance(self.cost, bool) or not isinstance(self.cost, (int, float))
                or self.cost < 0 or not math.isfinite(self.cost)):
            raise ValueError("attempt cost must be finite and non-negative")
        if not isinstance(self.accepted, bool):
            raise ValueError("accepted must be a boolean")
        if not isinstance(self.status, AttemptStatus):
            raise ValueError("status must be an AttemptStatus")
        if not isinstance(self.reports, tuple) or any(
            not isinstance(report, EvaluationReport) for report in self.reports
        ):
            raise ValueError("reports must be a tuple of EvaluationReport values")
        if self.detail is not None and (
            not isinstance(self.detail, str) or not self.detail.strip()
        ):
            raise ValueError("attempt detail must be non-empty when supplied")
        if self.feedback_fingerprint is not None and (
            not isinstance(self.feedback_fingerprint, str)
            or len(self.feedback_fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in self.feedback_fingerprint.lower())
        ):
            raise ValueError("feedback fingerprint must be a SHA-256 digest")

    def to_dict(self) -> dict[str, Any]:
        return {"attempt": self.attempt, "candidate": self.candidate.to_dict() if self.candidate else None,
                "score": self.score.to_dict() if self.score else None, "feedback_fingerprint": self.feedback_fingerprint,
                "accepted": self.accepted, "cost": self.cost, "status": self.status.value,
                "reports": [r.to_dict() for r in self.reports], "detail": self.detail}


@dataclass(frozen=True)
class ControllerPolicy:
    max_attempts: int = 8
    stagnation_window: int = 3
    max_cost: float = 100.0
    max_seconds: float = 3600.0
    max_evaluator_failures: int = 2
    oscillation_window: int = 6
    stop_on_safety_regression: bool = True
    no_safe_improvement_window: int = 2

    def __post_init__(self) -> None:
        if any(type(v) is not int or v <= 0 for v in (
            self.max_attempts, self.stagnation_window, self.max_evaluator_failures,
            self.oscillation_window,
            self.no_safe_improvement_window,
        )):
            raise ValueError("policy count limits must be positive integers")
        if (isinstance(self.max_cost, bool) or isinstance(self.max_seconds, bool)
                or not isinstance(self.max_cost, (int, float)) or not math.isfinite(self.max_cost)
                or not isinstance(self.max_seconds, (int, float)) or not math.isfinite(self.max_seconds)
                or self.max_cost < 0 or self.max_seconds < 0):
            raise ValueError("cost and time limits must be finite and non-negative")
        if not isinstance(self.stop_on_safety_regression, bool):
            raise ValueError("stop_on_safety_regression must be a boolean")


@dataclass(frozen=True)
class RepairLoopResult:
    best_candidate: CandidateReference
    best_score: StructuredScore
    attempts: tuple[AttemptRecord, ...]
    stop_reason: StopReason
    unresolved_failure_categories: tuple[str, ...]
    next_human_action: str
    total_cost: float

    def __post_init__(self) -> None:
        if not isinstance(self.best_candidate, CandidateReference):
            raise ValueError("best_candidate must be a CandidateReference")
        if not isinstance(self.best_score, StructuredScore):
            raise ValueError("best_score must be a StructuredScore")
        if not isinstance(self.attempts, tuple) or any(
            not isinstance(attempt, AttemptRecord) for attempt in self.attempts
        ):
            raise ValueError("attempts must be a tuple of AttemptRecord values")
        if not isinstance(self.stop_reason, StopReason):
            raise ValueError("stop_reason must be a StopReason")
        if not isinstance(self.unresolved_failure_categories, tuple) or any(
            not isinstance(value, str) or not value
            for value in self.unresolved_failure_categories
        ):
            raise ValueError("unresolved failure categories must be non-empty strings")
        if (isinstance(self.total_cost, bool)
                or not isinstance(self.total_cost, (int, float))
                or self.total_cost < 0 or not math.isfinite(self.total_cost)):
            raise ValueError("total cost must be finite and non-negative")
        if not self.next_human_action:
            raise ValueError("next human action must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {"best_candidate": self.best_candidate.to_dict(), "best_score": self.best_score.to_dict(),
                "attempts": [a.to_dict() for a in self.attempts], "stop_reason": self.stop_reason.value,
                "unresolved_failure_categories": list(self.unresolved_failure_categories),
                "next_human_action": self.next_human_action, "total_cost": self.total_cost}
