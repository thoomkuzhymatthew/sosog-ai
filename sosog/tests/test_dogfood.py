"""End-to-end dogfood wiring test using fake Bedrock and persistence."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from sosog.dogfood import run_worker_trace_dogfood


def trace(job_id, attempt):
    worktree = f"/opt/sosog/worktrees/{job_id}"
    events = [
        {
            "type": "sosog.job.started", "timestamp": "2026-08-24T10:00:00Z",
            "job_id": job_id, "attempt": attempt, "worker": job_id,
            "sandbox": "workspace-write",
            "git": {"worktree": worktree, "base_commit": "abc"},
        },
        {
            "type": "item.completed",
            "item": {
                "type": "file_change",
                "changes": [{"path": f"{worktree}/src/work.py", "kind": "update"}],
            },
        },
        {
            "type": "sosog.job.finished", "timestamp": "2026-08-24T10:01:00Z",
            "job_id": job_id, "attempt": attempt, "status": "succeeded",
            "exit_status": 0, "usage_events": [],
        },
    ]
    return "\n".join(json.dumps(event) for event in events) + "\n"


class FakeBedrock:
    def __init__(self):
        self.embedding_calls = 0
        self.label_calls = 0

    def invoke_model(self, **kwargs):
        body = json.loads(kwargs["body"])
        if "inputText" in body:
            self.embedding_calls += 1
            center = 0.0 if "family-a" in body["inputText"] else 10.0
            payload = {"embedding": [center, center]}
        else:
            self.label_calls += 1
            payload = {"content": [{
                "type": "text",
                "text": json.dumps({
                    "name": f"Worker family {self.label_calls}",
                    "description": "Makes a bounded code change and verifies it.",
                }),
            }]}
        return {"body": io.BytesIO(json.dumps(payload).encode())}


class FakeStore:
    def __init__(self):
        self.episodes = []
        self.task_types = []
        self.assignments = []
        self.outcomes = []
        self.classifications = []

    def record_episode(self, row):
        self.episodes.append(row); return True

    def record_task_type(self, row):
        self.task_types.append(row); return True

    def assign_episode_task_type(self, episode_id, task_type_id):
        self.assignments.append((episode_id, task_type_id)); return True

    def update_episode_outcome(self, episode_id, **outcome):
        self.outcomes.append((episode_id, outcome)); return True

    def record_classification(self, row):
        self.classifications.append(row); return True


class DogfoodTests(unittest.TestCase):
    def test_two_worker_families_flow_through_all_persisted_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for family in ("family-a", "family-b"):
                for attempt in range(3):
                    path = root / f"{family}-{attempt}.jsonl"
                    path.write_text(trace(family, f"{attempt:03d}"))
                    paths.append(path)
            store = FakeStore()
            client = FakeBedrock()

            result = run_worker_trace_dogfood(
                paths,
                store=store,
                artifact_dir=root / "artifacts",
                bedrock_client=client,
                min_cluster_size=2,
                min_samples=1,
                min_complete_runs=2,
            )

        self.assertEqual(len(result.episodes), 6)
        self.assertEqual(len(result.clusters), 2)
        self.assertEqual(sorted(len(c.member_episode_ids) for c in result.clusters), [3, 3])
        self.assertEqual(client.embedding_calls, 6)
        self.assertEqual(client.label_calls, 2)
        self.assertEqual(len(store.task_types), 2)
        self.assertEqual(len(store.assignments), 6)
        self.assertEqual(store.outcomes, [])
        self.assertEqual(len(store.classifications), 2)
        self.assertEqual(result.summary()["actions"], [
            "FULL_CRYSTALLIZE", "FULL_CRYSTALLIZE",
        ])


if __name__ == "__main__":
    unittest.main()
