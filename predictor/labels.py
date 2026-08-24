"""LEGACY, research-only route labels and audit overrides.

New code must use ``promotion_engine.classifier``, ``promotion_engine.taxonomy``,
and ``promotion_engine.audit``. This module remains unchanged for the
milestone-17 research paths in ``predictor/regret.py``,
``scripts/run_m17_predictor.py``, and ``scripts/run_m17_research_snapshot.py``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .contracts import FailurePattern, Route, TaskFeatures


@dataclass(frozen=True)
class TaskLabel:
    vertical: str
    task_id: str
    route: Route
    source: str
    failure_pattern: str
    needs_review: bool
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["route"] = self.route.value
        return value


def automatic_label(feature: TaskFeatures) -> TaskLabel:
    pattern = FailurePattern(feature.failure_pattern)
    if feature.artifact_flag or feature.ambiguity_signal or pattern == FailurePattern.ARTIFACT:
        route, reason, review = Route.LEAVE, "artifact or ambiguity signal", False
    elif feature.pass_rate <= 0.2:
        route, reason, review = Route.DROP, "pass rate is at or below 2/10", False
    elif feature.pass_rate >= 0.9 and feature.distinct_passing_skeletons == 1:
        route, reason, review = Route.PROMOTE, "promotion stability bar met", False
    elif (
        feature.pass_rate >= 0.9
        and feature.distinct_passing_skeletons >= 2
        and feature.prefix_ends_before_write
    ):
        route, reason, review = Route.DECOMPOSE, "stable read prefix before volatile writes", False
    elif 0.3 <= feature.pass_rate <= 0.8 and pattern == FailurePattern.AGENT_WANDERED:
        route, reason, review = Route.LIFT, "bounded genuine agent inconsistency", False
    else:
        route, reason, review = Route.LEAVE, "categorizer coverage boundary", True
    return TaskLabel(
        vertical=feature.vertical,
        task_id=feature.task_id,
        route=route,
        source="AUTOMATIC",
        failure_pattern=pattern.value,
        needs_review=review,
        rationale=reason,
    )


def apply_override(label: TaskLabel, override: dict[str, Any] | None) -> TaskLabel:
    if not override:
        return label
    return TaskLabel(
        vertical=label.vertical,
        task_id=label.task_id,
        route=Route(override.get("route", label.route.value)),
        source="HUMAN_AUDITED",
        failure_pattern=override.get("failure_pattern", label.failure_pattern),
        needs_review=False,
        rationale=override.get("rationale", label.rationale),
    )


def categorizer_audit(
    automatic: list[TaskLabel], overrides: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    audited = [label for label in automatic if label.task_id in overrides]
    comparable = [
        label
        for label in audited
        if overrides[label.task_id].get("failure_pattern") is not None
    ]
    correct = sum(
        label.failure_pattern == overrides[label.task_id]["failure_pattern"]
        for label in comparable
    )
    labels = sorted(
        set(item.failure_pattern for item in comparable)
        | {overrides[item.task_id]["failure_pattern"] for item in comparable}
    )
    per_class: dict[str, Any] = {}
    for name in labels:
        tp = sum(
            item.failure_pattern == name
            and overrides[item.task_id]["failure_pattern"] == name
            for item in comparable
        )
        fp = sum(
            item.failure_pattern == name
            and overrides[item.task_id]["failure_pattern"] != name
            for item in comparable
        )
        fn = sum(
            item.failure_pattern != name
            and overrides[item.task_id]["failure_pattern"] == name
            for item in comparable
        )
        per_class[name] = {
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "support": sum(
                overrides[item.task_id]["failure_pattern"] == name for item in comparable
            ),
        }
    return {
        "audited_count": len(audited),
        "comparable_failure_pattern_count": len(comparable),
        "accuracy": correct / len(comparable) if comparable else None,
        "automatic_pattern_counts": dict(Counter(item.failure_pattern for item in audited)),
        "per_class": per_class,
        "note": "Precision/recall are null when an audited sample has no predictions or support for a class.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.features.read_text())
    overrides = json.loads(args.overrides.read_text()) if args.overrides else {}
    overrides = overrides.get("tasks", overrides)
    features = [TaskFeatures.from_dict(item) for item in data.get("features", data)]
    automatic = [automatic_label(item) for item in features]
    labels = [apply_override(item, overrides.get(item.task_id)) for item in automatic]
    payload = {
        "schema_version": 1,
        "labels": [item.to_dict() for item in labels],
        "categorizer_audit": categorizer_audit(automatic, overrides),
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
