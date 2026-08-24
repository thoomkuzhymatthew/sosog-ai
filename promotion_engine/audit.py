"""Human overrides and calibration audits for promotion candidates."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from .contracts import PromotionAction


def _validated_action(action: Any) -> str:
    """Return a serialized promotion action or reject an unknown value."""

    try:
        return PromotionAction(action).value
    except (TypeError, ValueError) as exc:
        valid = ", ".join(item.value for item in PromotionAction)
        raise ValueError(
            f"unsupported promotion action {action!r}; expected one of: {valid}"
        ) from exc


def apply_override(
    candidate: dict[str, Any], override: dict[str, Any] | None
) -> dict[str, Any]:
    """Apply a human override to one serialized promotion candidate.

    Candidates use the shape emitted inside ``build_promotion_plan``'s
    ``candidates`` list. As in the legacy audit machinery, a missing override
    preserves the automatic result while marking its source explicitly.
    """

    audited = deepcopy(candidate)
    if not override:
        audited["source"] = "AUTOMATIC"
        return audited

    audited["action"] = _validated_action(
        override.get("action", candidate["action"])
    )
    audited["source"] = "HUMAN_AUDITED"

    evidence = audited.setdefault("evidence", {})
    evidence["review_required"] = False
    if "rationale" in override:
        evidence["reason"] = override["rationale"]
    elif "reason" in override:
        evidence["reason"] = override["reason"]
    return audited


def categorizer_audit(
    automatic: list[dict[str, Any]], overrides: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Measure automatic/human action agreement on reviewed candidates."""

    audited = [item for item in automatic if item["task_id"] in overrides]
    comparable = [
        item
        for item in audited
        if overrides[item["task_id"]].get("action") is not None
    ]
    override_actions = {
        item["task_id"]: _validated_action(overrides[item["task_id"]]["action"])
        for item in comparable
    }
    correct = sum(
        item["action"] == override_actions[item["task_id"]]
        for item in comparable
    )
    labels = sorted(
        {item["action"] for item in comparable}
        | set(override_actions.values())
    )
    per_class: dict[str, Any] = {}
    for name in labels:
        tp = sum(
            item["action"] == name
            and override_actions[item["task_id"]] == name
            for item in comparable
        )
        fp = sum(
            item["action"] == name
            and override_actions[item["task_id"]] != name
            for item in comparable
        )
        fn = sum(
            item["action"] != name
            and override_actions[item["task_id"]] == name
            for item in comparable
        )
        per_class[name] = {
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "support": sum(
                override_actions[item["task_id"]] == name
                for item in comparable
            ),
        }
    return {
        "audited_count": len(audited),
        "comparable_action_count": len(comparable),
        "accuracy": correct / len(comparable) if comparable else None,
        "automatic_action_counts": dict(Counter(item["action"] for item in audited)),
        "per_class": per_class,
        "note": "Precision/recall are null when an audited sample has no predictions or support for a class.",
    }
