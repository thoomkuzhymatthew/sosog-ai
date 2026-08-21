#!/usr/bin/env python3
"""Create or verify the isolated sosog_research schema on the configured DB."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DDL = ROOT / "infra" / "aws" / "sql" / "001_sosog_research.sql"


def connect():
    import psycopg

    required = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise SystemExit("missing database environment: " + ", ".join(missing))
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
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    with connect() as connection, connection.cursor() as cursor:
        if args.check:
            cursor.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'sosog_research'
                ORDER BY table_name
                """
            )
            tables = [row[0] for row in cursor.fetchall()]
            expected = [
                "artifacts", "budget_events", "router_predictions", "runs",
                "task_features", "task_runs",
            ]
            if tables != expected:
                raise SystemExit(f"schema mismatch: expected={expected}, actual={tables}")
            print("sosog_research schema is ready")
            return
        cursor.execute(DDL.read_text())
    print("initialized sosog_research schema")


if __name__ == "__main__":
    main()
