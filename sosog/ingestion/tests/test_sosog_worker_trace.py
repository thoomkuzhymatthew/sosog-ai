"""Focused worker-trace adapter tests with no live services."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sosog.ingestion.adapters.sosog_worker_trace import (
    ingest_worker_trace,
    normalize_worker_trace,
)


def event_trace(*, status="succeeded", exit_status=0, job_id="family-a", attempt="001"):
    worktree = f"/opt/sosog/worktrees/{job_id}"
    return [
        {
            "type": "sosog.job.started", "timestamp": "2026-08-24T10:00:00Z",
            "job_id": job_id, "attempt": attempt, "worker": job_id,
            "sandbox": "workspace-write",
            "git": {"worktree": worktree, "base_commit": "abc123"},
        },
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "python -m pytest -q; printf 'secret-output'",
                "aggregated_output": "person@example.com secret-output",
                "exit_code": 0,
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "file_change",
                "changes": [{"path": f"{worktree}/src/customer.py", "kind": "update"}],
            },
        },
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "Contact person@example.com"},
        },
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 999, "output_tokens": 999},
        },
        {
            "type": "sosog.job.finished", "timestamp": "2026-08-24T10:01:00Z",
            "job_id": job_id, "attempt": attempt, "status": status,
            "exit_status": exit_status,
            "usage_events": [{"input_tokens": 100, "output_tokens": 20}],
        },
    ]


class FakeStore:
    def __init__(self, succeeds=True):
        self.succeeds = succeeds
        self.rows = []

    def record_episode(self, row):
        self.rows.append(row)
        return self.succeeds


class WorkerTraceTests(unittest.TestCase):
    def test_normalizes_and_drops_raw_command_output_and_message_text(self):
        episode = normalize_worker_trace(event_trace(), raw_ref={"sha256": "a" * 64})

        self.assertTrue(episode.outcome.success)
        self.assertEqual(episode.outcome.success_source, "programmatic_verifier")
        self.assertEqual(episode.cost.tokens_in, 100)
        self.assertEqual(episode.cost.tokens_out, 20)
        self.assertEqual([call["name"] for call in episode.calls], [
            "run_tests", "edit_files", "report_result",
        ])
        rendered = json.dumps(episode.as_dict())
        self.assertNotIn("person@example.com", rendered)
        self.assertNotIn("secret-output", rendered)
        self.assertNotIn("customer.py", rendered)
        self.assertNotIn("/opt/sosog", rendered)
        self.assertIn("[REDACTED:", rendered)
        self.assertEqual(episode.annotations["vertical"], "sosog_internal")

    def test_finished_failure_is_a_complete_programmatic_failure(self):
        episode = normalize_worker_trace(event_trace(status="failed", exit_status=1))

        self.assertEqual(episode.outcome.status, "COMPLETE")
        self.assertIs(episode.outcome.success, False)

    def test_mismatched_or_incomplete_attempt_is_rejected(self):
        mismatch = event_trace()
        mismatch[-1]["attempt"] = "002"
        with self.assertRaisesRegex(ValueError, "different attempts"):
            normalize_worker_trace(mismatch)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            normalize_worker_trace(event_trace()[:-1])

    def test_ingest_archives_before_persisting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "trace.jsonl"
            source.write_text("\n".join(json.dumps(item) for item in event_trace()) + "\n")
            store = FakeStore()

            episode = ingest_worker_trace(
                source, store=store, artifact_dir=root / "artifacts"
            )

            self.assertEqual(store.rows[0]["episode_id"], episode.episode_id)
            self.assertTrue(episode.raw_ref["uri"].startswith("file:"))
            self.assertEqual(len(list((root / "artifacts").rglob("*.jsonl"))), 1)

    def test_store_rejection_is_not_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "trace.jsonl"
            source.write_text("\n".join(json.dumps(item) for item in event_trace()) + "\n")
            with self.assertRaisesRegex(RuntimeError, "store rejected"):
                ingest_worker_trace(
                    source, store=FakeStore(False), artifact_dir=root / "artifacts"
                )

    def test_matching_existing_episode_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "trace.jsonl"
            source.write_text("\n".join(json.dumps(item) for item in event_trace()) + "\n")
            first_store = FakeStore()
            first = ingest_worker_trace(
                source, store=first_store, artifact_dir=root / "artifacts"
            )

            class ExistingStore(FakeStore):
                def get_episode(self, episode_id):
                    return first_store.rows[0]

            existing_store = ExistingStore()
            second = ingest_worker_trace(
                source, store=existing_store, artifact_dir=root / "artifacts"
            )

            self.assertEqual(second.episode_id, first.episode_id)
            self.assertEqual(existing_store.rows, [])


if __name__ == "__main__":
    unittest.main()
