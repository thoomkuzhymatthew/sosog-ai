#!/usr/bin/env python3
"""Evaluate frozen v0 on an audited RDS snapshot and persist predictions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from predictor.contracts import TaskFeatures  # noqa: E402
from predictor.regret import evaluate  # noqa: E402
from predictor.router_v0 import predict  # noqa: E402


def connect():
    import psycopg

    return psycopg.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=8,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot_id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT vertical, task_id, features, oracle_route,
                   oracle_label_source, costs_by_route
            FROM sosog_research.task_features
            WHERE snapshot_id = %s
            ORDER BY vertical, task_id
            """,
            (args.snapshot_id,),
        )
        records = cursor.fetchall()
    if not records:
        raise SystemExit(f"snapshot has no task features: {args.snapshot_id}")
    missing_oracle = [f"{row[0]}:{row[1]}" for row in records if not row[3]]
    if missing_oracle:
        raise SystemExit(
            "snapshot is not audit-frozen; missing oracle labels: "
            + ", ".join(missing_oracle[:20])
        )

    corpus = {
        "schema_version": 1,
        "snapshot_id": args.snapshot_id,
        "tasks": [
            {
                "features": row[2],
                "oracle_route": row[3],
                "oracle_label_source": row[4],
                "costs_by_route": row[5] or {},
            }
            for row in records
        ],
    }
    result = evaluate(corpus)
    result["snapshot_id"] = args.snapshot_id
    heldout = {
        (item["vertical"], item["task_id"]): item
        for item in result["held_out_tasks"]
    }
    split_by_task = {
        (vertical, task_id): split
        for vertical, value in result["splits"].items()
        for split in ("train", "held_out")
        for task_id in value[split]
    }

    prediction_rows = []
    for record in corpus["tasks"]:
        feature = TaskFeatures.from_dict(record["features"])
        prediction = predict(feature)
        evaluation = heldout.get((feature.vertical, feature.task_id), {})
        prediction_rows.append(
            (
                args.snapshot_id,
                "v0",
                feature.vertical,
                feature.task_id,
                split_by_task.get((feature.vertical, feature.task_id), "unassigned"),
                prediction.route.value,
                prediction.confidence,
                prediction.expected_savings,
                evaluation.get("regret_usd"),
                evaluation.get("unsafe_promotion"),
                json.dumps(prediction.to_dict()),
            )
        )
    with connect() as connection, connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO sosog_research.router_predictions
                (snapshot_id, router_version, vertical, task_id, split,
                 predicted_route, confidence, expected_savings, regret_usd,
                 safety_error, prediction)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (snapshot_id, router_version, vertical, task_id)
            DO UPDATE SET
                split = excluded.split,
                predicted_route = excluded.predicted_route,
                confidence = excluded.confidence,
                expected_savings = excluded.expected_savings,
                regret_usd = excluded.regret_usd,
                safety_error = excluded.safety_error,
                prediction = excluded.prediction
            """,
            prediction_rows,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        f"evaluated {len(prediction_rows)} tasks; "
        f"distance=${result['distance_to_north_star_usd']}"
    )


if __name__ == "__main__":
    main()
