"""Narrow runtime contract shared by independently generated executors.

Generated family modules accept already-structured intent. Natural-language
parsing is evaluated separately and its output remains untrusted until the
executor's schema and state-consistency gates pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ExecutionStatus(StrEnum):
    """Terminal state of a deterministic execution attempt."""

    COMPLETED = "COMPLETED"
    DEFERRED = "DEFERRED"
    FAILED = "FAILED"


class ToolClient(Protocol):
    """Small adapter implemented by the benchmark and customer runtimes."""

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute one named tool and return its decoded result."""


@dataclass(frozen=True)
class ExecutionResult:
    """Auditable result returned by every generated family executor."""

    status: ExecutionStatus
    reason: str
    writes_executed: int
    model_calls: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.writes_executed < 0:
            raise ValueError("writes_executed cannot be negative")
        if self.model_calls < 0:
            raise ValueError("model_calls cannot be negative")
        if self.status == ExecutionStatus.DEFERRED and self.writes_executed != 0:
            raise ValueError("a deferred execution must not have performed writes")
