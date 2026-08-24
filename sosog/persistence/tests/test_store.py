"""Unit tests for the PostgreSQL store without a live database."""

from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from sosog.persistence.store import SosogStore, StoreConfig


class FakeCursor:
    def __init__(self, rows=None, description=None, error=None, rowcount=1):
        self.rows = list(rows or [])
        self.description = description or []
        self.error = error
        self.rowcount = rowcount
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

    def test_operational_writes_are_plain_inserts_and_serialize_json(self):
        cases = [
            ("record_artifact", {
                "artifact_id": "a-1", "kind": "candidate", "uri": "s3://b/a",
                "sha256": "a" * 64, "metadata": {"immutable": True},
            }, "artifacts", [{"immutable": True}]),
            ("record_proposal", {
                "proposal_id": "p-1", "task_type_id": "tt-1", "version": 1,
                "status": "DRAFT", "artifact_id": "a-1", "metadata": {"owner": "worker"},
                "evidence": {"source": "trace"},
            }, "proposals", [{"owner": "worker"}, {"source": "trace"}]),
            ("record_repair_run", {
                "repair_run_id": "rr-1", "proposal_id": "p-1", "attempt_number": 0,
                "status": "ACCEPTED", "score": {"safe": 3},
                "evidence": {"suite": "locked"},
            }, "repair_runs", [{"safe": 3}, {"suite": "locked"}]),
            ("record_budget_event", {
                "budget_event_id": "be-1", "event_kind": "MODEL", "amount_usd": 0.02,
                "input_tokens": 10, "model": "model-1", "metadata": {"tier": "repair"},
            }, "budget_events", [{"tier": "repair"}]),
        ]
        for method, row, table, json_values in cases:
            with self.subTest(method=method):
                cursor = FakeCursor()
                store, _ = make_store(cursor)
                self.assertTrue(getattr(store, method)(row))
                sql, params = cursor.executions[0]
                self.assertIn(f"INSERT INTO sosog_v1.{table}", sql)
                self.assertNotIn("ON CONFLICT", sql)
                decoded = [json.loads(item) for item in params if isinstance(item, str)
                           and item[:1] in ("{", "[")]
                for expected in json_values:
                    self.assertIn(expected, decoded)

    def test_operational_reads_are_scoped_and_ordered(self):
        cases = [
            ("get_artifact", ("a-1",), "artifact_id = %s", ("a-1",)),
            ("list_artifacts", (), "ORDER BY created_at ASC, artifact_id ASC", ("default",)),
            ("get_proposal", ("p-1",), "proposal_id = %s", ("p-1",)),
            ("list_proposals", ("tt-1",), "ORDER BY created_at ASC, proposal_id ASC", ("tt-1",)),
            ("list_repair_runs", ("p-1",), "ORDER BY attempt_number ASC", ("p-1",)),
            ("list_budget_events", (), "ORDER BY created_at ASC, budget_event_id ASC", ("default",)),
            ("get_review_item", ("rv-1",), "review_item_id = %s", ("rv-1",)),
            ("list_review_items", (), "ORDER BY created_at ASC, review_item_id ASC",
             ("default", "PENDING")),
        ]
        for method, args, sql_fragment, expected_params in cases:
            with self.subTest(method=method):
                cursor = FakeCursor(rows=[{"id": "one"}])
                store, _ = make_store(cursor)
                getattr(store, method)(*args)
                sql, params = cursor.executions[0]
                self.assertIn(sql_fragment, sql)
                self.assertEqual(params, expected_params)

    def test_review_creation_forces_pending_and_decision_is_guarded(self):
        cursor = FakeCursor()
        store, _ = make_store(cursor)
        self.assertTrue(store.create_review_item({
            "review_item_id": "rv-1", "review_type": "HUMAN_SAFETY_REVIEW",
            "subject_type": "PROPOSAL", "subject_id": "p-1",
            "context": {"candidate_sha256": "a" * 64}, "status": "APPROVED",
        }))
        self.assertTrue(store.decide_review_item(
            "rv-1", status="APPROVED", decision={"reason": "checked"}, reviewer="human-1"
        ))
        create_sql, create_params = cursor.executions[0]
        self.assertIn("'PENDING'", create_sql)
        self.assertNotIn("APPROVED", create_params)
        decision_sql, decision_params = cursor.executions[1]
        self.assertIn("status = 'PENDING'", decision_sql)
        self.assertIn("decided_at = now()", decision_sql)
        self.assertEqual(json.loads(decision_params[1]), {"reason": "checked"})
        self.assertEqual(decision_params, ("APPROVED", decision_params[1], "human-1", "rv-1"))

    def test_review_decision_rejects_invalid_terminal_status(self):
        store = SosogStore(StoreConfig())
        with self.assertRaisesRegex(ValueError, "APPROVED or REJECTED"):
            store.decide_review_item(
                "rv-1", status="PENDING", decision={}, reviewer="human-1"
            )

    def test_review_decision_reports_when_pending_guard_did_not_match(self):
        store, _ = make_store(FakeCursor(rowcount=0))
        self.assertFalse(store.decide_review_item(
            "rv-1", status="REJECTED", decision={"reason": "unsafe"}, reviewer="human-1"
        ))

    def test_operational_writes_validate_required_fields_before_connecting(self):
        methods = [
            ("record_artifact", {}), ("record_proposal", {}),
            ("record_repair_run", {}), ("record_budget_event", {}),
            ("create_review_item", {}),
        ]
        for method, value in methods:
            with self.subTest(method=method):
                store = SosogStore(
                    StoreConfig(), connection_factory=lambda: self.fail("connected")
                )
                with self.assertRaises(ValueError):
                    getattr(store, method)(value)

    def test_operations_migration_is_idempotent_and_constrained(self):
        migration = (
            Path(__file__).parents[3] / "infra/aws/sql/004_sosog_v1_operations.sql"
        ).read_text()
        for table in ("artifacts", "proposals", "repair_runs", "budget_events", "review_items"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS sosog_v1.{table}", migration)
        self.assertEqual(migration.count("engagement_id text NOT NULL DEFAULT 'default'"), 5)
        self.assertIn("UNIQUE (proposal_id, attempt_number)", migration)
        self.assertIn("UNIQUE (engagement_id, task_type_id, version)", migration)
        self.assertIn("status IN ('PENDING', 'APPROVED', 'REJECTED')", migration)
        self.assertIn("'WORKER_BLOCKED'", migration)
        self.assertIn("candidate_fingerprint ~ '^[0-9a-fA-F]{64}$'", migration)
        self.assertIn("feedback_fingerprint ~ '^[0-9a-fA-F]{64}$'", migration)
        self.assertIn("review_items_one_pending_subject_idx", migration)
        self.assertIn("WHERE status = 'PENDING'", migration)
        self.assertIn("amount_usd >= 0", migration)
        self.assertIn("jsonb_typeof(score) = 'object'", migration)
        self.assertIn("episode_id text REFERENCES sosog_v1.episodes", migration)
        self.assertNotIn("job_id text REFERENCES", migration)
        upper = migration.upper()
        self.assertNotIn("DROP TABLE", upper)
        self.assertNotIn("TRUNCATE", upper)
        self.assertNotIn("ON CONFLICT", upper)


if __name__ == "__main__":
    unittest.main()
