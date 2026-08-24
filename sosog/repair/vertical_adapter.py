"""Runtime-checkable dependency boundaries for repair and evaluation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import (
    CandidateReference,
    EvaluationReport,
    EvaluationTier,
    RepairFeedback,
    RepairWorkerResult,
    SuiteManifest,
)


@runtime_checkable
class LockedEvaluator(Protocol):
    def suite_manifest(self, tier: EvaluationTier) -> SuiteManifest: ...
    def evaluate(self, candidate: CandidateReference, tier: EvaluationTier) -> EvaluationReport: ...


@runtime_checkable
class RepairWorker(Protocol):
    def repair(
        self, candidate: CandidateReference, feedback: RepairFeedback
    ) -> CandidateReference | RepairWorkerResult: ...


@runtime_checkable
class VerticalAdapter(LockedEvaluator, Protocol):
    def historical_cost_for(self, task_family: str) -> float: ...
