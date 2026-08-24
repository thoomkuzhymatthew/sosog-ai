"""Focused tests for client trace ingestion without a database."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from predictor.features import skeleton
from sosog.ingestion.pipeline import ingest_file


class FakeStore:
    def __init__(self):
        self.rows = []

    def record_episode(self, value):
        self.rows.append(value)
        return True


def mapping(**changes):
    value = {
        "input_format": "jsonl",
        "episode_id_path": "id",
        "source_trace_id_path": "trace_id",
        "started_at_path": "started",
        "completed_at_path": "completed",
        "status_path": "status",
        "calls_path": "actions",
        "call_name_key": "tool",
        "call_arguments_key": "args",
        "call_is_write_key": "write",
        "call_result_key": "result",
        "cost_usd_path": "usage.usd",
        "tokens_in_path": "usage.input",
        "tokens_out_path": "usage.output",
        "model_path": "usage.model",
        "annotations_path": "annotations",
    }
    value.update(changes)
    return value


def record(**changes):
    value = {
        "id": "ep-1",
        "trace_id": "trace-1",
        "started": "2026-08-24T10:00:00Z",
        "completed": "2026-08-24T10:01:00Z",
        "status": "COMPLETE",
        "actions": [{"tool": "charge", "args": {"amount": 12}, "write": True, "result": "ok"}],
        "usage": {"usd": 0.04, "input": 100, "output": 20, "model": "example-model"},
        "annotations": {"tenant": "demo"},
    }
    value.update(changes)
    return value


class PipelineTests(unittest.TestCase):
    def ingest(self, raw, configured=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / "export.jsonl"
        body = (json.dumps(raw) + "\n").encode()
        source.write_bytes(body)
        store = FakeStore()
        episodes = ingest_file(source, configured or mapping(), store=store, artifact_dir=root / "artifacts")
        return episodes, store, root, body

    def test_clean_end_to_end_normalizes_archives_and_persists(self):
        episodes, store, root, body = self.ingest(record())

        self.assertEqual(len(episodes), 1)
        episode = episodes[0]
        self.assertIsNone(episode.task_type_id)
        self.assertEqual(episode.cost.tokens_in, 100)
        self.assertEqual(skeleton(episode.calls), (episode.calls[0]["signature"],))
        self.assertEqual(store.rows[0]["outcome_status"], "COMPLETE")
        digest = hashlib.sha256(body).hexdigest()
        self.assertEqual(store.rows[0]["raw_artifact_sha256"], digest)
        self.assertEqual(len(list((root / "artifacts").rglob(f"{digest}.jsonl"))), 1)

    def test_explicit_programmatic_success_is_preserved(self):
        configured = mapping(success_path="verifier.ok", success_source="programmatic_verifier")
        _, store, _, _ = self.ingest(record(verifier={"ok": False}), configured)
        self.assertIs(store.rows[0]["outcome_success"], False)
        self.assertEqual(store.rows[0]["outcome_success_source"], "programmatic_verifier")

    def test_missing_success_is_unknown_and_never_false(self):
        configured = mapping(success_path="verifier.ok", success_source="client_label")
        episode, store, _, _ = self.ingest(record(), configured)
        self.assertIsNone(episode[0].outcome.success)
        self.assertEqual(episode[0].outcome.success_source, "unknown")
        self.assertIsNone(store.rows[0]["outcome_success"])

    def test_sensitive_call_data_is_redacted_before_persistence(self):
        raw = record(actions=[{
            "tool": "lookup", "args": {"email": "person@example.com", "safe": "yes"},
            "result": {"card_number": "4111111111111111", "answer": 3},
        }])
        _, store, _, _ = self.ingest(raw)
        persisted = store.rows[0]["calls"][0]
        self.assertEqual(persisted["arguments"]["email"], "[REDACTED]")
        self.assertEqual(persisted["result"]["card_number"], "[REDACTED]")
        self.assertNotIn("person@example.com", json.dumps(store.rows[0]))
        self.assertNotIn("4111111111111111", json.dumps(store.rows[0]))

    def test_structural_call_name_is_preserved_while_pii_name_is_redacted(self):
        configured = mapping(call_name_key="name")
        raw = record(actions=[{
            "name": "lookup_customer",
            "args": {"name": "Ada Lovelace"},
            "result": {"name": "Ada Lovelace"},
        }])
        _, store, _, _ = self.ingest(raw, configured)
        persisted = store.rows[0]["calls"][0]
        self.assertEqual(persisted["name"], "lookup_customer")
        self.assertEqual(persisted["arguments"]["name"], "[REDACTED]")
        self.assertEqual(persisted["result"]["name"], "[REDACTED]")

    def test_malformed_record_is_rejected_after_raw_is_archived(self):
        malformed = record()
        del malformed["trace_id"]
        with self.assertRaisesRegex(ValueError, "raw record 0 rejected"):
            self.ingest(malformed)

    def test_all_records_validate_before_any_are_persisted(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / "export.jsonl"
        malformed = record(id="ep-2", trace_id="trace-2")
        del malformed["status"]
        source.write_text(
            "\n".join((json.dumps(record()), json.dumps(malformed))) + "\n"
        )
        store = FakeStore()

        with self.assertRaisesRegex(ValueError, "raw record 1 rejected"):
            ingest_file(source, mapping(), store=store, artifact_dir=root / "artifacts")

        self.assertEqual(store.rows, [])


if __name__ == "__main__":
    unittest.main()
