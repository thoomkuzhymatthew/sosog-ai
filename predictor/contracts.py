"""Shared, dependency-free contracts for predictor inputs and outputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Route(StrEnum):
    PROMOTE = "PROMOTE"
    DECOMPOSE = "DECOMPOSE"
    LIFT = "LIFT"
    GATED_PARSER = "GATED_PARSER"
    LEAVE = "LEAVE"
    DROP = "DROP"


class FailurePattern(StrEnum):
    AGENT_WANDERED = "agent-wandered"
    VOLATILE_TAIL = "volatile-tail"
    ARTIFACT = "artifact"
    MIXED = "mixed"
    NOT_APPLICABLE = "n/a"
    NEEDS_REVIEW = "needs-review"


class DivergencePoint(StrEnum):
    EARLY = "early"
    LATE = "late"
    NONE = "none"


@dataclass(frozen=True)
class TaskFeatures:
    vertical: str
    task_id: str
    pass_rate: float
    actual_n: int
    distinct_passing_skeletons: int
    longest_common_read_prefix_len: int = 0
    prefix_ends_before_write: bool = False
    write_arg_variance_across_passes: dict[str, Any] = field(default_factory=dict)
    first_diverge_point: str = DivergencePoint.NONE.value
    failure_pattern: str = FailurePattern.NOT_APPLICABLE.value
    artifact_flag: bool = False
    ambiguity_signal: bool = False
    m2_baseline_cost: float = 0.0

    def __post_init__(self) -> None:
        if not self.vertical:
            raise ValueError("vertical must be non-empty")
        if not self.task_id:
            raise ValueError("task_id must be non-empty")
        if not 0.0 <= self.pass_rate <= 1.0:
            raise ValueError("pass_rate must be between 0 and 1")
        if self.actual_n < 1:
            raise ValueError("actual_n must be at least 1")
        if self.distinct_passing_skeletons < 0:
            raise ValueError("distinct_passing_skeletons cannot be negative")
        if self.longest_common_read_prefix_len < 0:
            raise ValueError("longest_common_read_prefix_len cannot be negative")
        if self.m2_baseline_cost < 0:
            raise ValueError("m2_baseline_cost cannot be negative")
        FailurePattern(self.failure_pattern)
        DivergencePoint(self.first_diverge_point)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskFeatures":
        known = {item.name for item in cls.__dataclass_fields__.values()}
        return cls(**{key: val for key, val in value.items() if key in known})


@dataclass(frozen=True)
class RoutePrediction:
    vertical: str
    task_id: str
    route: Route
    confidence: float
    expected_savings: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["route"] = self.route.value
        return result
