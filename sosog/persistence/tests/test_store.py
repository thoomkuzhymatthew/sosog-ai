"""Unit tests for the PostgreSQL store without a live database."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from sosog.persistence.store import SosogStore, StoreConfig


class FakeCursor:
    def __init__(self, rows=None, description=None, error=None):
        self.rows = list(rows or [])
        self.description = description or []
        self.error = error
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, parameters):
        if self.error:
            raise self.error
        self.executions.append((sql, parameters))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.entries = 0

    def __enter__(self):
        self.entries += 1
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.fake_cursor


def make_store(cursor, *, required=False):
    connection = FakeConnection(cursor)
    config = StoreConfig(db_required=required)
    return SosogStore(config, connection_factory=lambda: connection), connection


class StoreTests(unittest.TestCase):
    def test_config_uses_product_database_environment(self):
        environment = {
            "DB_HOST": "db.internal", "DB_PORT": "5433",
            "SOSOG_DB_NAME": "sosog_v1", "DB_USER": "sosog",
            "DB_PASSWORD": "secret", "SOSOG_DB_SSLMODE": "verify-full",
        }
        with patch.dict(os.environ, environment, clear=True):
            config = StoreConfig.from_env()

        self.assertEqual(config.db_name, "sosog_v1")
        self.assertEqual(config.db_port, 5433)
        self.assertEqual(config.db_sslmode, "verify-full")
        self.assertTrue(config.database_configured)

    def test_database_tls_is_required_by_default(self):
        self.assertEqual(StoreConfig().db_sslmode, "require")

    def test_record_episode_serializes_json_and_uses_defaults(self):
        cursor = FakeCursor()
        store, connection = make_store(cursor)

        self.assertTrue(store.record_episode(
        {
            "episode_id": "ep-1",
            "source_trace_id": "trace-1",
            "outcome_status": "COMPLETE",
            "calls": [{"tool": "search"}],
        }))

        sql, params = cursor.executions[0]
        self.assertIn("INSERT INTO sosog_v1.episodes", sql)
        self.assertEqual(params[1], "default")
        self.assertEqual(params[6], "unknown")
        self.assertEqual(json.loads(params[8]), [{"tool": "search"}])
        self.assertEqual(json.loads(params[-1]), {})
        self.assertEqual(connection.entries, 1)

    def test_other_writes_are_plain_inserts(self):
        cases = [
        (
            "record_task_type",
            {
                "task_type_id": "tt-1",
                "name": "Refund",
                "description": "Issue a refund",
                "source": "AUTO_CLUSTERED",
                "representative_episode_ids": ["ep-1"],
            },
            "task_types",
        ),
        (
            "record_classification",
            {
                "classification_id": "cl-1",
                "task_type_id": "tt-1",
                "classifier_version": "v1",
                "features": {"n": 3},
                "internal_action": "FULL_CRYSTALLIZE",
                "product_category": "FULLY_CRYSTALLIZABLE",
                "evidence": {"passes": 3},
                "confidence": 0.9,
            },
            "classifications",
        ),
        ]
        for method, row, table in cases:
            with self.subTest(method=method):
                cursor = FakeCursor()
                store, _ = make_store(cursor)
                self.assertTrue(getattr(store, method)(row))
                sql, _ = cursor.executions[0]
                self.assertIn(f"INSERT INTO sosog_v1.{table}", sql)
                self.assertNotIn("ON CONFLICT", sql)

    def test_episode_analysis_updates_are_scoped_and_guard_evidence(self):
        cursor = FakeCursor()
        store, _ = make_store(cursor)

        self.assertTrue(store.assign_episode_task_type("ep-1", "tt-1"))
        self.assertTrue(store.update_episode_outcome(
            "ep-1", success=True, success_source="llm_judged",
            confidence=0.8, rationale="The write completed.",
        ))

        assign_sql, assign_params = cursor.executions[0]
        self.assertIn("SET task_type_id", assign_sql)
        self.assertEqual(assign_params, ("tt-1", "ep-1"))
        outcome_sql, outcome_params = cursor.executions[1]
        self.assertIn("outcome_success_source = 'unknown'", outcome_sql)
        self.assertEqual(outcome_params[0:3], (True, "llm_judged", 0.8))
        self.assertEqual(json.loads(outcome_params[3]), {
            "outcome_judge_rationale": "The write completed.",
        })

    def test_episode_analysis_updates_require_identifiers(self):
        store = SosogStore(StoreConfig())
        with self.assertRaises(ValueError):
            store.assign_episode_task_type("", "tt-1")
        with self.assertRaises(ValueError):
            store.update_episode_outcome(
                "ep-1", success=None, success_source="", confidence=None
            )

    def test_tuple_read_uses_cursor_description(self):
        cursor = FakeCursor(
        rows=[("ep-1", "COMPLETE")],
        description=[("episode_id",), ("outcome_status",)],
        )
        store, _ = make_store(cursor)
        self.assertEqual(store.get_episode("ep-1"), {
            "episode_id": "ep-1", "outcome_status": "COMPLETE",
        })
        self.assertEqual(cursor.executions[0][1], ("ep-1",))

    def test_mapping_list_read_and_history_order(self):
        cursor = FakeCursor(rows=[{"classification_id": "cl-1"}, {"classification_id": "cl-2"}])
        store, _ = make_store(cursor)
        rows = store.list_classification_history("tt-1")
        self.assertEqual([row["classification_id"] for row in rows], ["cl-1", "cl-2"])
        self.assertIn("ORDER BY created_at ASC", cursor.executions[0][0])

    def test_latest_classification_orders_newest_first(self):
        cursor = FakeCursor(rows=[{"classification_id": "cl-2"}])
        store, _ = make_store(cursor)
        self.assertEqual(store.get_latest_classification("tt-1"), {"classification_id": "cl-2"})
        self.assertIn("ORDER BY created_at DESC", cursor.executions[0][0])
        self.assertIn("LIMIT 1", cursor.executions[0][0])

    def test_get_classification_reads_by_primary_key(self):
        cursor = FakeCursor(rows=[{"classification_id": "cl-1"}])
        store, _ = make_store(cursor)

        self.assertEqual(store.get_classification("cl-1"), {"classification_id": "cl-1"})
        self.assertEqual(cursor.executions[0][1], ("cl-1",))

    def test_unconfigured_store_degrades_to_empty_results(self):
        store = SosogStore(StoreConfig())
        self.assertFalse(store.record_episode(
        {"episode_id": "ep-1", "source_trace_id": "trace", "outcome_status": "NEW"}
        ))
        self.assertIsNone(store.get_episode("ep-1"))
        self.assertEqual(store.list_task_types(), [])

    def test_database_error_is_remembered_and_disables_retries(self):
        attempts = 0
        def fail():
            nonlocal attempts
            attempts += 1
            raise OSError("offline")
        store = SosogStore(StoreConfig(), connection_factory=fail)
        self.assertEqual(store.list_task_types(), [])
        self.assertEqual(store.list_task_types(), [])
        self.assertEqual(attempts, 1)
        self.assertEqual(store.last_db_error, "OSError: offline")

    def test_required_database_reraises_operation_error(self):
        cursor = FakeCursor(error=RuntimeError("write failed"))
        store, _ = make_store(cursor, required=True)
        with self.assertRaisesRegex(RuntimeError, "write failed"):
            store.record_task_type(
            {"task_type_id": "tt", "name": "n", "description": "d", "source": "s"}
        )

    def test_missing_required_fields_are_rejected_before_connecting(self):
        def unexpected_connection():
            self.fail("connected")
        store = SosogStore(StoreConfig(), connection_factory=unexpected_connection)
        with self.assertRaisesRegex(ValueError, "source_trace_id"):
            store.record_episode({"episode_id": "ep", "outcome_status": "NEW"})


if __name__ == "__main__":
    unittest.main()
