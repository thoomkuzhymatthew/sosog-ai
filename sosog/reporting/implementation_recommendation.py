"""Deterministic implementation options with an explicit human boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from promotion_engine.contracts import PromotionAction


class ImplementationPath(StrEnum):
    API_SERVICE = "API_SERVICE"
    MERGE_REQUEST = "MERGE_REQUEST"
    RETAINED_AGENTIC = "RETAINED_AGENTIC"
    HUMAN_WORKFLOW = "HUMAN_WORKFLOW"
    COLLECT_MORE_EVIDENCE = "COLLECT_MORE_EVIDENCE"


@dataclass(frozen=True)
class ImplementationOption:
    path: ImplementationPath
    rationale: str
    eligible: bool
    prerequisites: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.path, ImplementationPath):
            raise ValueError("path must be an ImplementationPath")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("rationale must be non-empty")
        if type(self.eligible) is not bool:
            raise ValueError("eligible must be a boolean")
        if not isinstance(self.prerequisites, tuple) or any(
            not isinstance(value, str) or not value.strip()
            for value in self.prerequisites
        ):
            raise ValueError("prerequisites must be non-empty strings")
        if self.eligible and self.prerequisites:
            raise ValueError("eligible options cannot have unmet prerequisites")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path.value,
            "rationale": self.rationale,
            "eligible": self.eligible,
            "prerequisites": list(self.prerequisites),
        }


@dataclass(frozen=True)
class ImplementationRecommendation:
    action: str
    options: tuple[ImplementationOption, ...]
    human_decision_required: bool = True
    boundary: str = (
        "A human must choose and authorize an implementation path; this "
        "recommendation has not written, merged, approved, or deployed client code."
    )

    def __post_init__(self) -> None:
        supported = {item.value for item in PromotionAction} | {"FULLY_MANUAL"}
        if self.action not in supported:
            raise ValueError("unsupported recommendation action")
        if not isinstance(self.options, tuple) or not self.options or any(
            not isinstance(option, ImplementationOption) for option in self.options
        ):
            raise ValueError("recommendation requires validated options")
        if len({option.path for option in self.options}) != len(self.options):
            raise ValueError("implementation option paths must be unique")
        if self.human_decision_required is not True:
            raise ValueError("a human decision is always required")
        if not isinstance(self.boundary, str) or not self.boundary.strip():
            raise ValueError("human boundary must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "options": [option.to_dict() for option in self.options],
            "human_decision_required": self.human_decision_required,
            "boundary": self.boundary,
        }


def recommend_implementation(
    action: PromotionAction | str,
    *,
    client_repo_access: bool,
    repair_status: str | None = None,
    review_status: str | None = None,
) -> ImplementationRecommendation:
    """Derive proposal-only options; repository access never implies approval."""

    if type(client_repo_access) is not bool:
        raise ValueError("client_repo_access must be a boolean")
    action_name = action.value if isinstance(action, PromotionAction) else str(action)
    supported = {item.value for item in PromotionAction} | {"FULLY_MANUAL"}
    if action_name not in supported:
        raise ValueError(f"unsupported promotion action: {action_name}")
    for value, name in ((repair_status, "repair_status"), (review_status, "review_status")):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{name} must be non-empty when supplied")

    reviewed = review_status in {"APPROVED", "HUMAN_REVIEWED"}
    repair_ready = repair_status in {
        "PENDING_HUMAN_SAFETY_REVIEW", "HUMAN_REVIEWED", "APPROVED"
    }
    safe_to_propose_change = reviewed and repair_ready
    options: list[ImplementationOption] = []

    if action_name in {"FULL_CRYSTALLIZE", "RESPONSE_CRYSTALLIZE", "DECOMPOSE"}:
        options.append(ImplementationOption(
            ImplementationPath.API_SERVICE,
            "Expose the bounded automation behind a separately operated service interface.",
            safe_to_propose_change,
            () if safe_to_propose_change else ("complete repair evidence and human safety review",),
        ))
        mr_prerequisites = []
        if not client_repo_access:
            mr_prerequisites.append("client repository access")
        if not safe_to_propose_change:
            mr_prerequisites.append("complete repair evidence and human safety review")
        options.append(ImplementationOption(
            ImplementationPath.MERGE_REQUEST,
            "A reviewed change may be proposed in the client repository for independent review.",
            not mr_prerequisites,
            tuple(mr_prerequisites),
        ))
    elif action_name in {"LIFT", "RETAIN"}:
        options.append(ImplementationOption(
            ImplementationPath.RETAINED_AGENTIC,
            "Keep the task on an agentic execution path while preserving its safety controls.",
            True,
        ))
    elif action_name == "FULLY_MANUAL":
        options.append(ImplementationOption(
            ImplementationPath.HUMAN_WORKFLOW,
            "Retain a human-operated workflow because no automation action is supported.",
            True,
        ))
    else:  # DROP
        options.append(ImplementationOption(
            ImplementationPath.COLLECT_MORE_EVIDENCE,
            "Collect representative labeled evidence before selecting an implementation path.",
            True,
        ))

    # A human-operated fallback is always an eligible option.
    if action_name != "FULLY_MANUAL":
        options.append(ImplementationOption(
            ImplementationPath.HUMAN_WORKFLOW,
            "Keep the current human decision boundary while evidence or authorization is pending.",
            True,
        ))
    return ImplementationRecommendation(action_name, tuple(options))
