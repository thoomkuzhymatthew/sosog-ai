#!/usr/bin/env python3
"""Load one or more audited predictor corpora into a frozen RDS snapshot."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


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
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("corpora", nargs="+", type=Path)
    args = parser.parse_args()

    rows = []
    for path in args.corpora:
        corpus = json.loads(path.read_text())
        for item in corpus["tasks"]:
            features = item["features"]
            rows.append(
                (
                    args.snapshot_id,
                    features["vertical"],
                    str(features["task_id"]),
                    str(corpus.get("feature_version", "v0")),
                    json.dumps(features),
                    item.get("automatic_route") or item.get("m3_route"),
                    item.get("oracle_route"),
                    item.get("oracle_label_source"),
                    json.dumps(item.get("costs_by_route", {})),
                    json.dumps(item.get("audit", {})),
                )
            )
    with connect() as connection, connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO sosog_research.task_features
                (snapshot_id, vertical, task_id, feature_version, features,
                 automatic_route, oracle_route, oracle_label_source,
                 costs_by_route, audit)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s::jsonb)
            ON CONFLICT (snapshot_id, vertical, task_id, feature_version)
            DO UPDATE SET
                features = excluded.features,
                automatic_route = excluded.automatic_route,
                oracle_route = excluded.oracle_route,
                oracle_label_source = excluded.oracle_label_source,
                costs_by_route = excluded.costs_by_route,
                audit = excluded.audit
            """,
            rows,
        )
    print(f"loaded {len(rows)} task features into snapshot {args.snapshot_id}")


if __name__ == "__main__":
    main()
