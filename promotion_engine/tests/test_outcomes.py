from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from promotion_engine.outcomes import append_outcome, verify_outcome_ledger


def _record(event_id: str, stage: str = "AGENT_ATTEMPT") -> dict:
    return {
        "actor": "test-controller",
        "event_id": event_id,
        "evidence": {"trace_sha256": event_id * 4},
        "job_id": "airline-family-v1",
        "recorded_at": "2026-08-23T00:00:00+00:00",
        "stage": stage,
        "status": "PASSED",
    }


class OutcomeLedgerTests(unittest.TestCase):
    def test_outcome_ledger_is_hash_chained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outcomes.jsonl"
            first = append_outcome(path, _record("a"))
            second = append_outcome(path, _record("b", "INDEPENDENT_HELD_OUT"))
            records = verify_outcome_ledger(path)

        self.assertEqual(len(records), 2)
        self.assertEqual(second["previous_sha256"], first["record_sha256"])

    def test_outcome_ledger_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outcomes.jsonl"
            append_outcome(path, _record("a"))
            value = json.loads(path.read_text())
            value["status"] = "FAILED"
            path.write_text(json.dumps(value) + "\n")
            with self.assertRaisesRegex(ValueError, "record hash mismatch"):
                verify_outcome_ledger(path)

    def test_outcome_ledger_rejects_duplicate_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outcomes.jsonl"
            append_outcome(path, _record("a"))
            with self.assertRaisesRegex(ValueError, "duplicate event_id"):
                append_outcome(path, _record("a"))


if __name__ == "__main__":
    unittest.main()
