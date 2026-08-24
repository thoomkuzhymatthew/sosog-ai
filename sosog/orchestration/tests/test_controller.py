from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from sosog.orchestration.controller import run_repair_controller


class Ops:
    def start(self, unit): self.unit = unit
    def active_state(self, unit): return "inactive"
    def monotonic(self): return 0
    def sleep(self, seconds): raise AssertionError("successful fixture should not poll")


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"; self.repo.mkdir()
        self.worktree = self.root / "worktrees" / "job"; self.worktree.mkdir(parents=True)
        self.job = self.root / "jobs" / "job"; self.job.mkdir(parents=True)
        (self.job / "status").write_text("succeeded")
        self.trace = self.job / "traces" / "001"; self.trace.mkdir(parents=True)
        (self.trace / "circuit-breaker.json").write_text(json.dumps({"status": "passed"}))
    def tearDown(self): self.temp.cleanup()

    def test_freezes_only_allowed_regular_file(self):
        source = self.worktree / "pkg" / "proposal.py"; source.parent.mkdir(); source.write_text("safe")
        (self.trace / "changed-files.txt").write_text("pkg/proposal.py\n")
        result = run_repair_controller("job", self.root, self.repo, object(), ["pkg/proposal.py"], operations=Ops())
        self.assertEqual(result.status, "FROZEN_PENDING_EVALUATION")
        self.assertEqual((result.frozen_directory / "pkg/proposal.py").read_text(), "safe")
        self.assertEqual(
            json.loads((result.trace_directory / "circuit-breaker.json").read_text()),
            {"status": "passed"},
        )

    def test_rejects_path_symlink_and_circuit_breaker(self):
        outside = self.root / "outside"; outside.write_text("x")
        link = self.worktree / "link"; link.symlink_to(outside)
        (self.trace / "changed-files.txt").write_text("link\n")
        with self.assertRaises(ValueError):
            run_repair_controller("job", self.root, self.repo, object(), ["link"], operations=Ops())
        (self.trace / "circuit-breaker.json").write_text(json.dumps({"status": "failed"}))
        with self.assertRaises(PermissionError):
            run_repair_controller("job", self.root, self.repo, object(), ["link"], operations=Ops())
        with self.assertRaises(ValueError):
            run_repair_controller("../bad", self.root, self.repo, object(), ["link"], operations=Ops())

    def test_rejects_symlinked_worktree_root(self):
        outside = self.root / "outside-worktree"; outside.mkdir()
        self.worktree.rmdir()
        self.worktree.symlink_to(outside, target_is_directory=True)
        (self.trace / "changed-files.txt").write_text("proposal.py\n")
        with self.assertRaises(ValueError):
            run_repair_controller("job", self.root, self.repo, object(), ["proposal.py"], operations=Ops())

    def test_blocked_worker_returns_without_polling_or_freezing(self):
        (self.job / "status").write_text("blocked_auth")
        result = run_repair_controller(
            "job", self.root, self.repo, object(), ["proposal.py"], operations=Ops()
        )
        self.assertEqual(result.status, "WORKER_BLOCKED")
        self.assertEqual(result.detail, "blocked_auth")
        self.assertIsNone(result.frozen_directory)

    def test_rejects_duplicate_changed_paths(self):
        source = self.worktree / "proposal.py"
        source.write_text("safe")
        (self.trace / "changed-files.txt").write_text("proposal.py\nproposal.py\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            run_repair_controller(
                "job", self.root, self.repo, object(), ["proposal.py"], operations=Ops()
            )

    def test_waits_for_worker_to_create_job_and_worktree(self):
        shutil.rmtree(self.worktree)
        shutil.rmtree(self.job)
        outer = self

        class DelayedOps:
            def __init__(self):
                self.now = 0
                self.polls = 0
            def start(self, unit):
                raise AssertionError("dispatcher already started this worker")
            def active_state(self, unit):
                return "active"
            def monotonic(self):
                return self.now
            def sleep(self, seconds):
                self.now += seconds
                self.polls += 1
                outer.worktree.mkdir(parents=True)
                source = outer.worktree / "proposal.py"
                source.write_text("safe")
                trace = outer.job / "traces" / "001"
                trace.mkdir(parents=True)
                (outer.job / "status").write_text("succeeded")
                (trace / "circuit-breaker.json").write_text(
                    json.dumps({"status": "passed"})
                )
                (trace / "changed-files.txt").write_text("proposal.py\n")

        operations = DelayedOps()
        result = run_repair_controller(
            "job", self.root, self.repo, object(), ["proposal.py"],
            operations=operations, start_worker=False, poll_seconds=0.1,
        )
        self.assertEqual(result.status, "FROZEN_PENDING_EVALUATION")
        self.assertEqual(operations.polls, 1)


if __name__ == "__main__": unittest.main()
