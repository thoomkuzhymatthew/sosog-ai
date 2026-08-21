"""Cost-weighted regret and explicit unsafe-promotion evaluation."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .contracts import Route, TaskFeatures
from .router_v0 import predict
from .splits import build_splits


ESTIMATED_COST_FACTORS = {
    Route.PROMOTE: 0.02,
    Route.DECOMPOSE: 0.75,
    Route.LIFT: 1.10,
    Route.GATED_PARSER: 0.50,
    Route.LEAVE: 1.00,
    Route.DROP: 0.00,
}

# An incompatible cheaper route is not allowed to appear better than the
# oracle merely because its correctness loss is missing from token spend.
MISMATCH_PENALTY_FACTORS = {
    Route.PROMOTE: 1.00,
    Route.DECOMPOSE: 0.50,
    Route.LIFT: 0.35,
    Route.GATED_PARSER: 0.35,
    Route.LEAVE: 0.00,
    Route.DROP: 2.00,
}


def route_cost(record: dict[str, Any], route: Route) -> tuple[float, str]:
    measured = record.get("costs_by_route") or {}
    value = measured.get(route.value)
    if value is not None:
        return float(value), "MEASURED"
    baseline = float(record["features"]["m2_baseline_cost"])
    return baseline * ESTIMATED_COST_FACTORS[route], "ESTIMATED"


def evaluate_task(record: dict[str, Any]) -> dict[str, Any]:
    feature = TaskFeatures.from_dict(record["features"])
    prediction = predict(feature)
    oracle = Route(record["oracle_route"])
    oracle_cost, oracle_source = route_cost(record, oracle)
    predicted_cost, predicted_source = route_cost(record, prediction.route)
    mismatch_penalty = 0.0
    if prediction.route != oracle:
        mismatch_penalty = (
            feature.m2_baseline_cost * MISMATCH_PENALTY_FACTORS[prediction.route]
        )
    adjusted_predicted_cost = predicted_cost + mismatch_penalty
    regret = max(0.0, adjusted_predicted_cost - oracle_cost)
    regret_pct = regret / feature.m2_baseline_cost if feature.m2_baseline_cost else None
    unsafe_promotion = prediction.route == Route.PROMOTE and oracle in {
        Route.LEAVE,
        Route.DROP,
    }
    return {
        "vertical": feature.vertical,
        "task_id": feature.task_id,
        "oracle_route": oracle.value,
        "predicted_route": prediction.route.value,
        "confidence": prediction.confidence,
        "expected_savings_usd": prediction.expected_savings,
        "oracle_cost_usd": round(oracle_cost, 9),
        "oracle_cost_source": oracle_source,
        "predicted_cost_usd": round(predicted_cost, 9),
        "predicted_cost_source": predicted_source,
        "mismatch_penalty_usd": round(mismatch_penalty, 9),
        "regret_usd": round(regret, 9),
        "regret_pct_of_baseline": round(regret_pct, 9) if regret_pct is not None else None,
        "route_correct": prediction.route == oracle,
        "unsafe_promotion": unsafe_promotion,
        "oracle_label_source": record.get("oracle_label_source", "UNKNOWN"),
    }


def bootstrap_sum_ci(values: list[float], *, seed: int = 17017) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(seed)
    samples = []
    for _ in range(4000):
        samples.append(sum(rng.choice(values) for _ in values))
    samples.sort()
    return [samples[int(0.025 * len(samples))], samples[int(0.975 * len(samples))]]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = sum(float(row.get("regret_usd") or 0.0) for row in rows)
    values = [float(row.get("regret_usd") or 0.0) for row in rows]
    return {
        "tasks": len(rows),
        "route_accuracy": (
            sum(bool(row["route_correct"]) for row in rows) / len(rows) if rows else None
        ),
        "route_confusion": {
            f"{oracle}->{predicted}": count
            for (oracle, predicted), count in sorted(
                Counter((row["oracle_route"], row["predicted_route"]) for row in rows).items()
            )
        },
        "regret_usd": round(baseline, 9),
        "regret_usd_bootstrap_95_ci": (
            [round(item, 9) for item in bootstrap_sum_ci(values)] if values else None
        ),
        "unsafe_promotion_count": sum(bool(row["unsafe_promotion"]) for row in rows),
        "estimated_oracle_cost_count": sum(
            row["oracle_cost_source"] == "ESTIMATED" for row in rows
        ),
        "estimated_predicted_cost_count": sum(
            row["predicted_cost_source"] == "ESTIMATED" for row in rows
        ),
    }


def evaluate(corpus: dict[str, Any]) -> dict[str, Any]:
    records = corpus["tasks"]
    splits = build_splits(
        [
            {
                "vertical": item["features"]["vertical"],
                "task_id": item["features"]["task_id"],
                "oracle_route": item["oracle_route"],
            }
            for item in records
        ]
    )
    rows = [evaluate_task(item) for item in records]
    held_out_ids = {
        (vertical, task_id)
        for vertical, split in splits.items()
        for task_id in split["held_out"]
    }
    held_out = [row for row in rows if (row["vertical"], row["task_id"]) in held_out_ids]
    by_vertical: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in held_out:
        by_vertical[row["vertical"]].append(row)
    return {
        "schema_version": 1,
        "router": "v0",
        "evaluation_split": "held_out",
        "split_method": "70/30 SHA-256 rank by task ID within vertical and oracle-route stratum",
        "cost_model": {
            "estimated_route_cost_factors": {
                key.value: value for key, value in ESTIMATED_COST_FACTORS.items()
            },
            "mismatch_penalty_factors": {
                key.value: value for key, value in MISMATCH_PENALTY_FACTORS.items()
            },
            "note": "Measured route costs win when available. Estimated costs and correctness-loss penalties are explicitly flagged.",
        },
        "splits": splits,
        "per_vertical": {
            vertical: summarize(items) for vertical, items in sorted(by_vertical.items())
        },
        "aggregate": summarize(held_out),
        "distance_to_north_star_usd": round(
            sum(float(row["regret_usd"]) for row in held_out), 9
        ),
        "held_out_tasks": sorted(held_out, key=lambda item: (item["vertical"], item["task_id"])),
        "all_task_route_accuracy": summarize(rows)["route_accuracy"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.corpus.read_text()))
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
