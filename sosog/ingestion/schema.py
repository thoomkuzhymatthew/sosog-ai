"""Versioned records at the client-trace ingestion boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class Outcome:
    status: str
    success: bool | None = None
    success_source: str = "unknown"
    confidence: float | None = None


@dataclass(frozen=True)
class Cost:
    usd: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    model: str | None = None


@dataclass(frozen=True)
class NormalizedEpisode:
    episode_id: str
    task_type_id: str | None
    source_trace_id: str
    started_at: Any
    completed_at: Any
    calls: list[dict[str, Any]]
    outcome: Outcome
    cost: Cost
    annotations: dict[str, Any] = field(default_factory=dict)
    raw_ref: dict[str, str] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_store_record(self) -> dict[str, Any]:
        """Translate the boundary schema to ``SosogStore.record_episode``."""
        metadata = {
            "schema_version": self.schema_version,
            "annotations": self.annotations,
            "cost": {
                "tokens_in": self.cost.tokens_in,
                "tokens_out": self.cost.tokens_out,
                "model": self.cost.model,
            },
        }
        return {
            "episode_id": self.episode_id,
            "task_type_id": self.task_type_id,
            "source_trace_id": self.source_trace_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "calls": self.calls,
            "outcome_status": self.outcome.status,
            "outcome_success": self.outcome.success,
            "outcome_success_source": self.outcome.success_source,
            "outcome_confidence": self.outcome.confidence,
            "cost_usd": self.cost.usd if self.cost.usd is not None else 0.0,
            "raw_artifact_uri": self.raw_ref.get("uri"),
            "raw_artifact_sha256": self.raw_ref.get("sha256"),
            "metadata": metadata,
        }

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
