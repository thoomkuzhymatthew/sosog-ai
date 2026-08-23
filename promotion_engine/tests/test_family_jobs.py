from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from promotion_engine.family_jobs import build_family_coding_jobs


def _plan() -> dict:
    return {
        "vertical": "airline",
        "candidates": [
            {
                "task_id": "1",
                "action": "FULL_CRYSTALLIZE",
                "evidence": {
                    "n": 7,
                    "pass_rate": 1.0,
                    "mean_cost_usd": 0.1,
                    "write_name_patterns": [["write"]],
                },
            }
        ],
    }


def _config() -> dict:
    return {
        "schema_version": 1,
        "vertical": "airline",
        "tau2_dependency": {
            "commit": "abc",
            "repository": "https://example.test/tau2.git",
            "runtime_path": "/opt/tau2",
        },
        "families": [
            {
                "family_id": "family",
                "job_id": "airline-family-v1",
                "action": "FULL_CRYSTALLIZE",
                "training_task_ids": ["1"],
                "evaluation_set_id": "heldout-v1",
                "allowed_write_tools": ["write"],
                "allowed_changed_paths": ["crystallized/airline/family.py"],
                "max_changed_files": 1,
                "max_diff_bytes": 1000,
                "module_path": "crystallized/airline/family.py",
                "test_path": "crystallized/airline/tests/test_family.py",
            }
        ],
    }


class FamilyJobTests(unittest.TestCase):
    def test_family_job_hides_eval_ids_and_hashes_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            traces = root / "metrics/m18_airline_promotion/training_traces"
            tasks = root / "metrics/m18_airline_promotion/training_tasks"
            traces.mkdir(parents=True)
            tasks.mkdir(parents=True)
            (traces / "family.jsonl").write_text('{"task_id":"1"}\n')
            (tasks / "family.json").write_text(json.dumps([{"id": "1"}]))
            jobs = build_family_coding_jobs(
                _plan(),
                _config(),
                artifact_root=root,
                controller_evaluation_hashes={"heldout-v1": "f" * 64},
            )

        self.assertEqual(len(jobs), 1)
        self.assertFalse(jobs[0]["manifest"]["evaluation"]["visible_to_worker"])
        self.assertNotIn("heldout_task_ids", jobs[0]["manifest"]["evaluation"])
        self.assertFalse(jobs[0]["manifest"]["permissions"]["may_deploy"])
        self.assertIn("Do not commit, merge, push, deploy", jobs[0]["prompt"])
        self.assertIn("SHA-256", jobs[0]["prompt"])

    def test_family_config_rejects_training_action_mismatch(self) -> None:
        config = _config()
        config["families"][0]["action"] = "DECOMPOSE"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "not DECOMPOSE"):
                build_family_coding_jobs(
                    _plan(),
                    config,
                    artifact_root=Path(directory),
                    controller_evaluation_hashes={"heldout-v1": "f" * 64},
                )


if __name__ == "__main__":
    unittest.main()
