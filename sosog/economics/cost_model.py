"""Deterministic, fail-closed task and portfolio cost projections."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from typing import Any, Iterable, Mapping

from promotion_engine.contracts import PromotionAction
from promotion_engine.taxonomy import client_category_for

from .inputs import CostAssumptions, EvidenceQuality, VolumeInput, decimal_string, decimal_value


CENT = Decimal("0.01")


class ProjectionAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    SCENARIO_ONLY = "SCENARIO_ONLY"
    UNAVAILABLE = "UNAVAILABLE"


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class TaskProjection:
    task_type_id: str
    action: str
    category: str
    period: str
    availability: ProjectionAvailability
    baseline_cost_usd: Decimal | None
    projected_cost_usd: Decimal | None
    claimed_savings_usd: Decimal | None
    formula: str
    assumptions: tuple[str, ...]
    sources: tuple[str, ...]
    quality: EvidenceQuality
    confidence: Decimal
    fallback_rate: Decimal | None
    savings_kind: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        amount = lambda value: None if value is None else decimal_string(money(value))
        return {
            "task_type_id": self.task_type_id, "action": self.action,
            "category": self.category, "period": self.period,
            "availability": self.availability.value,
            "baseline_cost_usd": amount(self.baseline_cost_usd),
            "projected_cost_usd": amount(self.projected_cost_usd),
            "claimed_savings_usd": amount(self.claimed_savings_usd),
            "formula": self.formula, "assumptions": list(self.assumptions),
            "sources": list(self.sources), "quality": self.quality.value,
            "confidence": decimal_string(self.confidence),
            "fallback_rate": None if self.fallback_rate is None else decimal_string(self.fallback_rate),
            "savings_kind": self.savings_kind, "reason": self.reason,
        }


def _repair_review(value: Mapping[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(value, Mapping):
        raise ValueError("locked repair evidence is missing")
    if value.get("tier") != "LOCKED":
        raise ValueError("repair evidence is not locked-evaluation evidence")
    reviewed_value = value.get("reviewed")
    if reviewed_value is not None and not isinstance(reviewed_value, bool):
        raise ValueError("locked evidence reviewed must be a boolean")
    status = value.get("status")
    allowed_statuses = {
        None, "PENDING_HUMAN_SAFETY_REVIEW", "HUMAN_REVIEWED",
        "APPROVED", "REJECTED",
    }
    if status not in allowed_statuses:
        raise ValueError("locked evidence has an unknown review status")
    if status == "REJECTED":
        raise ValueError("locked repair evidence was rejected")
    status_reviewed = status in {"HUMAN_REVIEWED", "APPROVED"}
    if reviewed_value is not None and reviewed_value is not status_reviewed:
        # With no explicit status, a boolean is the source of truth.
        if status is not None:
            raise ValueError("locked evidence review fields contradict each other")
    reviewed = reviewed_value is True if status is None else status_reviewed
    source = value.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("locked evidence source must be non-empty")
    return reviewed, source.strip()


def _locked_evidence(value: Mapping[str, Any] | None) -> tuple[Decimal, bool, str]:
    reviewed, source = _repair_review(value)
    assert value is not None
    rate_value = value.get("fallback_rate", value.get("failure_rate"))
    if rate_value is None and "passed" in value and "total" in value:
        total = decimal_value(value["total"], "locked total", minimum=Decimal("1"))
        passed = decimal_value(value["passed"], "locked passed")
        if total != total.to_integral_value() or passed != passed.to_integral_value():
            raise ValueError("locked passed and total must be whole case counts")
        if passed > total:
            raise ValueError("locked passed cannot exceed total")
        rate_value = (total - passed) / total
    rate = decimal_value(rate_value, "fallback_rate")
    if rate > 1:
        raise ValueError("fallback_rate must be between zero and one")
    return rate, reviewed, source


def project_task(
    volume: VolumeInput, costs: CostAssumptions, action: PromotionAction | str,
    repair_evidence: Mapping[str, Any] | None = None,
) -> TaskProjection:
    if volume.task_type_id != costs.task_type_id:
        raise ValueError("volume and cost task_type_id must match")
    try:
        internal = PromotionAction(action)
        category = client_category_for(internal)
        action_name = internal.value
    except ValueError:
        action_name = str(action)
        if action_name != "FULLY_MANUAL":
            raise ValueError(f"unsupported action: {action_name}") from None
        category = "FULLY_MANUAL"
    baseline = costs.current_agent_cost_usd * volume.unit_count
    quality = (EvidenceQuality.MEASURED if volume.quality is costs.quality is EvidenceQuality.MEASURED
               else EvidenceQuality.ESTIMATED)
    confidence = min(
        costs.confidence,
        Decimal("1") if quality is EvidenceQuality.MEASURED else Decimal("0.5"),
    )
    sources = (f"volume: {volume.source}", f"cost: {costs.source}")
    common = dict(task_type_id=volume.task_type_id, action=action_name, category=category,
                  period=volume.period.value, baseline_cost_usd=baseline, quality=quality,
                  confidence=confidence, sources=sources)
    if category in {"FULLY_AGENTIC", "FULLY_MANUAL", "INSUFFICIENT_EVIDENCE"}:
        return TaskProjection(**common, availability=ProjectionAvailability.AVAILABLE,
            projected_cost_usd=baseline, claimed_savings_usd=Decimal("0"), fallback_rate=None,
            formula="savings = 0 (category does not support claimed savings)", assumptions=(),
            savings_kind="PROJECTED", reason="No savings claimed for this category")
    if internal is PromotionAction.DECOMPOSE:
        per_unit = costs.prefix_cost_usd + costs.tail_fraction * costs.current_agent_cost_usd
        projected = per_unit * volume.unit_count
        formula = "volume * (prefix_cost + tail_fraction * current_agent_cost)"
        try:
            reviewed, evidence_source = _repair_review(repair_evidence)
        except ValueError as exc:
            return TaskProjection(**common, availability=ProjectionAvailability.UNAVAILABLE,
                projected_cost_usd=None, claimed_savings_usd=None,
                formula=formula,
                assumptions=(f"tail_fraction={decimal_string(costs.tail_fraction)}",),
                fallback_rate=None, savings_kind="NONE", reason=str(exc))
        availability = (ProjectionAvailability.AVAILABLE if reviewed
                        else ProjectionAvailability.SCENARIO_ONLY)
        return TaskProjection(**{**common, "sources": sources + (
                f"locked_evaluation: {evidence_source}",)}, availability=availability,
            projected_cost_usd=projected, claimed_savings_usd=max(Decimal("0"), baseline-projected),
            formula=formula,
            assumptions=(f"tail_fraction={decimal_string(costs.tail_fraction)}",),
            fallback_rate=None, savings_kind="PROJECTED",
            reason=None if reviewed else "Unreviewed repair evidence; scenario only")
    try:
        fallback, reviewed, evidence_source = _locked_evidence(repair_evidence)
    except ValueError as exc:
        return TaskProjection(**common, availability=ProjectionAvailability.UNAVAILABLE,
            projected_cost_usd=None, claimed_savings_usd=None,
            formula="volume * (fixed_automation_cost + fallback_rate * current_agent_cost)",
            assumptions=(), fallback_rate=None, savings_kind="NONE", reason=str(exc))
    projected = volume.unit_count * (costs.fixed_automation_cost_usd + fallback * costs.current_agent_cost_usd)
    availability = ProjectionAvailability.AVAILABLE if reviewed else ProjectionAvailability.SCENARIO_ONLY
    return TaskProjection(**{**common, "sources": sources + (f"locked_evaluation: {evidence_source}",)},
        availability=availability, projected_cost_usd=projected,
        claimed_savings_usd=max(Decimal("0"), baseline-projected),
        formula="volume * (fixed_automation_cost + fallback_rate * current_agent_cost)",
        assumptions=(f"locked_fallback_rate={decimal_string(fallback)}",), fallback_rate=fallback,
        savings_kind="PROJECTED", reason=None if reviewed else "Unreviewed repair evidence; scenario only")


@dataclass(frozen=True)
class PortfolioProjection:
    period: str
    tasks: tuple[TaskProjection, ...]
    baseline_cost_usd: Decimal
    projected_cost_usd: Decimal
    claimed_savings_usd: Decimal
    scenario_savings_usd: Decimal
    unavailable_task_count: int
    scenario_task_count: int

    def to_dict(self) -> dict[str, Any]:
        return {"period": self.period, "tasks": [task.to_dict() for task in self.tasks],
            "baseline_cost_usd": decimal_string(money(self.baseline_cost_usd)),
            "projected_cost_usd": decimal_string(money(self.projected_cost_usd)),
            "claimed_savings_usd": decimal_string(money(self.claimed_savings_usd)),
            "scenario_savings_usd": decimal_string(money(self.scenario_savings_usd)),
            "unavailable_task_count": self.unavailable_task_count,
            "scenario_task_count": self.scenario_task_count}


def project_portfolio(projections: Iterable[TaskProjection]) -> PortfolioProjection:
    tasks = tuple(sorted(projections, key=lambda item: item.task_type_id))
    if not tasks:
        raise ValueError("portfolio requires at least one projection")
    periods = {task.period for task in tasks}
    if len(periods) != 1:
        raise ValueError("portfolio task periods must match")
    available = [task for task in tasks if task.availability is ProjectionAvailability.AVAILABLE]
    scenarios = [task for task in tasks if task.availability is ProjectionAvailability.SCENARIO_ONLY]
    return PortfolioProjection(period=next(iter(periods)), tasks=tasks,
        baseline_cost_usd=sum((task.baseline_cost_usd or Decimal("0") for task in tasks), Decimal("0")),
        # Fail closed in the claimed portfolio: scenario-only or unavailable tasks
        # retain their current baseline instead of disappearing from the total.
        projected_cost_usd=sum(
            (task.projected_cost_usd if task in available else task.baseline_cost_usd) or Decimal("0")
            for task in tasks
        ),
        claimed_savings_usd=sum((task.claimed_savings_usd or Decimal("0") for task in available), Decimal("0")),
        scenario_savings_usd=sum((task.claimed_savings_usd or Decimal("0") for task in scenarios), Decimal("0")),
        unavailable_task_count=sum(task.availability is ProjectionAvailability.UNAVAILABLE for task in tasks),
        scenario_task_count=sum(task.availability is ProjectionAvailability.SCENARIO_ONLY for task in tasks))
