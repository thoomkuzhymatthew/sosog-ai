from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from sosog.orchestration.controller import ControllerResult
from sosog.repair.codex_worker import CodexRepairWorker, CodexRepairWorkerConfig
from sosog.repair.contracts import CandidateReference, RepairFeedback, StructuredScore

def feedback():
    return RepairFeedback(StructuredScore(0, 1, 2, 1, 2, 1, 2),
                          ("OWNERSHIP",), ("opaque-fingerprint",),
                          ("Validate ownership before writing.",))

class Harness:
    def __init__(self, root: Path, mode="success", cost=1.25):
        self.root, self.mode, self.cost = root, mode, cost
        self.enqueued = []; self.supervised = []; self.cost_reads = 0
        self.merge_calls = self.deploy_calls = 0
    def enqueue(self, *args, **kwargs): self.enqueued.append((args, kwargs))
    def supervisor(self, job_id, *args, **kwargs):
        self.supervised.append((job_id, kwargs))
        if self.mode == "failure": return ControllerResult("WORKER_FAILED")
        frozen = self.root / job_id; frozen.mkdir()
        artifact = frozen / "out" / "candidate.py"; artifact.parent.mkdir()
        if self.mode == "symlink": artifact.symlink_to(self.root / "secret")
        elif self.mode != "missing": artifact.write_bytes(b"candidate bytes")
        return ControllerResult("FROZEN_PENDING_EVALUATION", frozen)
    def read_cost(self, job_id, result): self.cost_reads += 1; return self.cost

class CodexWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.candidate = CandidateReference("a"*64, location="frozen/best.py")
    def tearDown(self): self.temp.cleanup()
    def worker(self, harness):
        return CodexRepairWorker(CodexRepairWorkerConfig(
            "repair", "Follow the visible contract.", "Two public regression tests.",
            ("out/candidate.py",), "out/candidate.py", self.root, self.root,
            "b"*40, 2, 1, 1000, harness.enqueue, harness.supervisor,
            harness.read_cost))

    def test_deterministic_prompt_and_job_id_contains_only_sanitized_context(self):
        locked_fixture = {"case_id": "LOCKED-CASE-SECRET",
                          "expected_answer": "EXPECTED-SECRET",
                          "raw_output": "RAW-SECRET"}
        first_h, second_h = Harness(self.root), Harness(self.root)
        self.worker(first_h)._job(self.candidate, feedback())
        first = self.worker(first_h); second = self.worker(second_h)
        one = first._job(self.candidate, feedback()); two = second._job(self.candidate, feedback())
        self.assertEqual(one, two)
        prompt = one[1]
        for secret in locked_fixture.values(): self.assertNotIn(secret, prompt)
        self.assertIn("OWNERSHIP", prompt); self.assertIn("opaque-fingerprint", prompt)

    def test_enqueues_and_supervises_once_without_double_start_and_hashes_candidate(self):
        harness = Harness(self.root); result = self.worker(harness).repair(self.candidate, feedback())
        self.assertEqual(result.candidate.digest, hashlib.sha256(b"candidate bytes").hexdigest())
        self.assertEqual(result.cost, 1.25); self.assertEqual(len(harness.enqueued), 1)
        self.assertEqual(len(harness.supervised), 1)
        self.assertTrue(harness.enqueued[0][1]["start_worker"])
        self.assertFalse(harness.supervised[0][1]["start_worker"])
        self.assertEqual((harness.merge_calls, harness.deploy_calls), (0, 0))

    def test_rejects_missing_and_symlink_artifacts(self):
        for mode in ("missing", "symlink"):
            with self.subTest(mode=mode):
                child = self.root / mode; child.mkdir(); harness = Harness(child, mode)
                with self.assertRaises(ValueError): self.worker(harness).repair(self.candidate, feedback())

    def test_supervisor_failure_and_invalid_measured_cost_fail_closed(self):
        with self.assertRaises(RuntimeError): self.worker(Harness(self.root, "failure")).repair(self.candidate, feedback())
        for cost in (None, float("nan"), -1, True):
            with self.subTest(cost=cost):
                child = self.root / str(cost); child.mkdir(); harness = Harness(child, cost=cost)
                with self.assertRaises(ValueError): self.worker(harness).repair(self.candidate, feedback())

if __name__ == "__main__": unittest.main()
