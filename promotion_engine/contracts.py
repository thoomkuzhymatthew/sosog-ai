"""Dependency-free contracts for trace promotion plans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PromotionAction(StrEnum):
    """The next treatment supported by trace evidence."""

    FULL_CRYSTALLIZE = "FULL_CRYSTALLIZE"
    RESPONSE_CRYSTALLIZE = "RESPONSE_CRYSTALLIZE"
    DECOMPOSE = "DECOMPOSE"
    LIFT = "LIFT"
    RETAIN = "RETAIN"
    DROP = "DROP"


@dataclass(frozen=True)
class PromotionEvidence:
    """Compact, auditable evidence behind one promotion decision."""

    n: int
    passes: int
    pass_rate: float
    mean_cost_usd: float
    write_name_patterns: tuple[tuple[str, ...], ...]
    read_prefix: tuple[str, ...]
    reason: str
    confidence: float
    review_required: bool
    proposed_next_stage: str

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ValueError("n must be at least 1")
        if not 0 <= self.passes <= self.n:
            raise ValueError("passes must be between zero and n")
        if not 0.0 <= self.pass_rate <= 1.0:
            raise ValueError("pass_rate must be between zero and one")
        if self.mean_cost_usd < 0:
            raise ValueError("mean_cost_usd cannot be negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between zero and one")
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if not self.proposed_next_stage:
            raise ValueError("proposed_next_stage must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "passes": self.passes,
            "pass_rate": self.pass_rate,
            "mean_cost_usd": self.mean_cost_usd,
            "write_name_patterns": [list(item) for item in self.write_name_patterns],
            "read_prefix": list(self.read_prefix),
            "reason": self.reason,
            "confidence": self.confidence,
            "review_required": self.review_required,
            "proposed_next_stage": self.proposed_next_stage,
        }


@dataclass(frozen=True)
class PromotionCandidate:
    """Promotion decision for a single benchmark task."""

    vertical: str
    task_id: str
    action: PromotionAction
    evidence: PromotionEvidence

    def __post_init__(self) -> None:
        if not self.vertical:
            raise ValueError("vertical must be non-empty")
        if not self.task_id:
            raise ValueError("task_id must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "vertical": self.vertical,
            "task_id": self.task_id,
            "action": self.action.value,
            "evidence": self.evidence.to_dict(),
        }
