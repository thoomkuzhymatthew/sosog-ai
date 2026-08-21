#!/usr/bin/env python3
"""Build the Retail M17 corpus, route it, and evaluate held-out regret."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from predictor.contracts import DivergencePoint, FailurePattern, Route, TaskFeatures  # noqa: E402
from predictor.features import extract_corpus_features, read_jsonl  # noqa: E402
from predictor.labels import TaskLabel, categorizer_audit  # noqa: E402
from predictor.regret import evaluate  # noqa: E402
from predictor.router_v0 import predict  # noqa: E402
from predictor.splits import build_splits  # noqa: E402


SUMMARY = ROOT / "metrics" / "m3_final_summary.json"
TRACES = ROOT / "traces" / "m3" / "retail_db_checkable_n10_final_valid.jsonl"
M11_ALIGNMENT = ROOT / "metrics" / "m11_decomposition_results.json"
M11_SCALE = ROOT / "metrics" / "m11_scale_results.json"
M12 = ROOT / "metrics" / "m12_lifting_task49_results.json"
AUDIT = ROOT / "config" / "m17_retail_route_audit.json"
CORPUS_OUT = ROOT / "metrics" / "m17_retail_labeled_corpus.json"
PREDICTIONS_OUT = ROOT / "metrics" / "m17_router_predictions.json"
REGRET_OUT = ROOT / "metrics" / "m17_router_regret.json"
SPLITS_OUT = ROOT / "metrics" / "m17_splits.json"

WRITE_TOOLS = {
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
}


def per_run_cost(summary: dict[str, Any]) -> float:
    runs = int(summary["runs"])
    if not runs:
        raise ValueError("measured summary has zero runs")
    for key in ("cost_total_cached_usd", "cost_from_usage_total_cached_usd", "total_cost_cached_usd"):
        if summary.get(key) is not None and float(summary[key]) != 0.0:
            return float(summary[key]) / runs
    raise ValueError(f"measured summary has no usable total cost: {sorted(summary)}")


def measured_costs() -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    decomposition = json.loads(M11_ALIGNMENT.read_text())
    for task_id, comparison in decomposition["comparisons"].items():
        result[task_id] = {
            Route.LEAVE.value: per_run_cost(comparison["baseline"]),
            Route.DECOMPOSE.value: per_run_cost(comparison["m11"]),
        }
    scale = json.loads(M11_SCALE.read_text())
    for task_id, item in scale["task_summaries"].items():
        result[task_id] = {
            Route.LEAVE.value: per_run_cost(item["summaries"]["baseline"]),
            Route.DECOMPOSE.value: per_run_cost(item["summaries"]["decomposed"]),
        }
    lifting = json.loads(M12.read_text())
    for task_id, item in lifting["task_summaries"].items():
        result[task_id] = {
            Route.LEAVE.value: per_run_cost(item["summaries"]["baseline"]),
            Route.LIFT.value: per_run_cost(item["summaries"]["lifted"]),
        }
    return result


def feature_with_updates(feature: TaskFeatures, **updates: Any) -> TaskFeatures:
    value = feature.to_dict()
    value.update(updates)
    return TaskFeatures.from_dict(value)


def build_retail_corpus() -> dict[str, Any]:
    summary = json.loads(SUMMARY.read_text())
    summary_by_task = {str(item["task_id"]): item for item in summary["per_task"]}
    audit = json.loads(AUDIT.read_text())["tasks"]
    alignment = json.loads(M11_ALIGNMENT.read_text())["alignment"]
    costs = measured_costs()

    extracted = extract_corpus_features(
        "retail",
        read_jsonl(TRACES),
        write_tools=WRITE_TOOLS,
        baseline_costs={
            task_id: float(item["m2_baseline_cost_cached_usd"])
            for task_id, item in summary_by_task.items()
        },
    )
    automatic_by_task = {item.task_id: item for item in extracted}
    if set(automatic_by_task) != set(summary_by_task):
        missing = sorted(set(summary_by_task) - set(automatic_by_task))
        extra = sorted(set(automatic_by_task) - set(summary_by_task))
        raise ValueError(f"trace/summary task mismatch; missing={missing}, extra={extra}")

    automatic_labels: list[TaskLabel] = []
    audit_overrides: dict[str, dict[str, Any]] = {}
    tasks = []
    m3_regressions = []
    for task_id, summary_item in sorted(
        summary_by_task.items(), key=lambda item: int(item[0])
    ):
        raw_feature = automatic_by_task[task_id]
        override = audit.get(task_id)
        if override:
            finalized = feature_with_updates(
                raw_feature,
                failure_pattern=override["failure_pattern"],
                artifact_flag=override["artifact_flag"],
                ambiguity_signal=override["ambiguity_signal"],
            )
            m3_route = Route(override["route"])
            oracle_route = Route(override["oracle_route"])
            label_source = (
                "M12_MEASURED"
                if task_id == "49"
                else "M11_MEASURED"
                if task_id in alignment
                else "M3_HUMAN_AUDITED"
            )
            audit_overrides[task_id] = {
                "failure_pattern": override["failure_pattern"],
                "route": override["route"],
            }
        else:
            finalized = feature_with_updates(
                raw_feature,
                failure_pattern=FailurePattern.NOT_APPLICABLE.value,
                artifact_flag=False,
                ambiguity_signal=False,
            )
            m3_route = Route.PROMOTE
            oracle_route = Route.PROMOTE
            label_source = "M3_STABILITY_SCREEN"

        if task_id in alignment:
            item = alignment[task_id]
            finalized = feature_with_updates(
                finalized,
                longest_common_read_prefix_len=int(item["safe_read_prefix_length"]),
                prefix_ends_before_write=True,
                first_diverge_point=DivergencePoint.LATE.value,
            )

        auto_pattern = raw_feature.failure_pattern
        automatic_labels.append(
            TaskLabel(
                vertical="retail",
                task_id=task_id,
                route=m3_route,
                source="AUTOMATIC_TRACE_PATTERN",
                failure_pattern=auto_pattern,
                needs_review=auto_pattern == FailurePattern.NEEDS_REVIEW.value,
                rationale="pre-audit trace categorizer output",
            )
        )

        prediction = predict(finalized)
        if prediction.route != m3_route:
            m3_regressions.append(
                {
                    "task_id": task_id,
                    "m3_route": m3_route.value,
                    "predicted_route": prediction.route.value,
                }
            )
        tasks.append(
            {
                "features": finalized.to_dict(),
                "automatic_failure_pattern": auto_pattern,
                "m3_route": m3_route.value,
                "oracle_route": oracle_route.value,
                "oracle_label_source": label_source,
                "oracle_rationale": override["rationale"] if override else "M3 promotion bar met.",
                "costs_by_route": costs.get(task_id, {}),
                "cost_note": (
                    "Measured matched-arm costs are included where M11/M12 exists; all other route costs are estimated by regret.py."
                ),
            }
        )

    return {
        "schema_version": 1,
        "vertical": "retail",
        "task_count": len(tasks),
        "trace_source": str(TRACES.relative_to(ROOT)),
        "summary_source": str(SUMMARY.relative_to(ROOT)),
        "audit_source": str(AUDIT.relative_to(ROOT)),
        "categorizer_audit": categorizer_audit(automatic_labels, audit_overrides),
        "m3_route_regression_count": len(m3_regressions),
        "m3_route_regressions": m3_regressions,
        "known_post_m3_oracle_changes": {
            "87": "LEAVE because M11 was cost-negative",
            "100": "LEAVE because M11 harmed correctness",
            "112": "LEAVE because M11 was cost-negative and within correctness noise",
        },
        "tasks": tasks,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="recompute and fail if checked-in artifacts differ",
    )
    args = parser.parse_args()
    corpus = build_retail_corpus()
    predictions = {
        "schema_version": 1,
        "router": "v0",
        "predictions": [
            predict(TaskFeatures.from_dict(item["features"])).to_dict()
            for item in corpus["tasks"]
        ],
    }
    split_payload = {
        "schema_version": 1,
        "method": "sha256 rank within vertical and oracle-route stratum; round(0.70 * stratum N) train",
        "verticals": build_splits(
            [
                {
                    **item["features"],
                    "oracle_route": item["oracle_route"],
                }
                for item in corpus["tasks"]
            ]
        ),
    }
    outputs = {
        CORPUS_OUT: corpus,
        PREDICTIONS_OUT: predictions,
        SPLITS_OUT: split_payload,
        REGRET_OUT: evaluate(corpus),
    }
    if args.check:
        mismatches = []
        for path, value in outputs.items():
            rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
            if not path.exists() or path.read_text() != rendered:
                mismatches.append(str(path.relative_to(ROOT)))
        if mismatches:
            raise SystemExit("stale M17 artifacts: " + ", ".join(mismatches))
        print("M17 artifacts are current")
        return
    for path, value in outputs.items():
        write_json(path, value)
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
