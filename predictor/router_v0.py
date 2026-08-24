"""LEGACY, research-only: auditable, zero-LLM-call v0 route predictor.

New code must use ``promotion_engine.classifier`` and
``promotion_engine.taxonomy``. This module remains unchanged for the milestone-17
research paths in ``predictor/regret.py``, ``scripts/run_m17_predictor.py``, and
``scripts/run_m17_research_snapshot.py``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import FailurePattern, Route, RoutePrediction, TaskFeatures


SAVINGS_FACTORS = {
    Route.PROMOTE: 0.98,
    Route.DECOMPOSE: 0.25,
    Route.LIFT: 0.0,
    Route.GATED_PARSER: 0.50,
    Route.LEAVE: 0.0,
    Route.DROP: 1.0,
}


def predict(feature: TaskFeatures) -> RoutePrediction:
    pattern = FailurePattern(feature.failure_pattern)
    if feature.pass_rate >= 0.9 and feature.distinct_passing_skeletons == 1:
        route = Route.PROMOTE
        confidence = 0.97 if feature.pass_rate == 1.0 else 0.92
        reason = ">=9/10 passes with one passing write skeleton"
    elif (
        feature.pass_rate >= 0.9
        and feature.distinct_passing_skeletons >= 2
        and feature.prefix_ends_before_write
    ):
        route = Route.DECOMPOSE
        confidence = 0.82
        reason = ">=9/10 passes, divergent skeletons, stable prefix ends before write"
    elif (
        0.3 <= feature.pass_rate <= 0.8
        and pattern == FailurePattern.AGENT_WANDERED
        and not feature.artifact_flag
    ):
        route = Route.LIFT
        confidence = 0.78
        reason = "mid-rate genuine inconsistency without artifact flag"
    elif feature.artifact_flag or feature.ambiguity_signal:
        route = Route.LEAVE
        confidence = 0.94
        reason = "artifact or ambiguity signal"
    elif feature.pass_rate <= 0.2:
        route = Route.DROP
        confidence = 0.95
        reason = "pass rate is at or below 2/10"
    else:
        route = Route.LEAVE
        confidence = 0.40
        reason = "coverage-bounded fallback"

    expected_savings = feature.m2_baseline_cost * SAVINGS_FACTORS[route]
    return RoutePrediction(
        vertical=feature.vertical,
        task_id=feature.task_id,
        route=route,
        confidence=confidence,
        expected_savings=round(expected_savings, 9),
        reason=reason,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.features.read_text())
    features = [TaskFeatures.from_dict(item) for item in data.get("features", data)]
    payload = {
        "schema_version": 1,
        "router": "v0",
        "predictions": [predict(item).to_dict() for item in features],
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
