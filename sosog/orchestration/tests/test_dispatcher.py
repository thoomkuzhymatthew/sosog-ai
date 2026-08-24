from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sosog.orchestration.dispatcher import enqueue_dynamic_job, enqueue_jobs


class DispatcherValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.geteuid_patcher = patch(
            "sosog.orchestration.dispatcher.os.geteuid", return_value=0
        )
        self.geteuid = self.geteuid_patcher.start()
        self.addCleanup(self.geteuid_patcher.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.agent_root = self.root / "agents"
        self.repo.mkdir()
        for name in ("prompts", "manifests", "queue"):
            (self.agent_root / name).mkdir(parents=True, exist_ok=True)
        self.base_commit = "a" * 40

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _job(self, **updates: str) -> dict[str, str]:
        (self.repo / "prompt.md").write_text("prompt", encoding="utf-8")
        (self.repo / "manifest.json").write_text("{}", encoding="utf-8")
        job = {
            "job_id": "safe-job",
            "prompt_path": "prompt.md",
            "prompt_sha256": hashlib.sha256(b"prompt").hexdigest(),
            "manifest_path": "manifest.json",
            "manifest_sha256": hashlib.sha256(b"{}").hexdigest(),
        }
        job.update(updates)
        return job

    def _git_result(self):
        result = unittest.mock.Mock()
        result.stdout = self.base_commit + "\n"
        return result

    def _manifest(self, job_id="dynamic"):
        return {"schema_version": 2, "job_id": job_id,
                "allowed_changed_paths": ["proposal.py"], "max_changed_files": 1,
                "max_diff_bytes": 1000, "require_changes": True,
                "permissions": {"may_commit": False, "may_merge": False,
                                "may_push": False, "may_deploy": False,
                                "network_access": False}}

    @patch("sosog.orchestration.dispatcher.tempfile.mkstemp")
    @patch("sosog.orchestration.dispatcher.shutil.copyfile")
    @patch("sosog.orchestration.dispatcher.subprocess.run")
    def test_rejects_non_root_before_subprocesses_or_writes(
        self, run, copyfile, mkstemp
    ) -> None:
        self.geteuid.return_value = 1000
        with self.assertRaisesRegex(PermissionError, "must be run as root"):
            enqueue_jobs([], self.agent_root, self.repo, self.base_commit)
        run.assert_not_called()
        copyfile.assert_not_called()
        mkstemp.assert_not_called()
        self.assertEqual(list((self.agent_root / "queue").iterdir()), [])

    @patch("sosog.orchestration.dispatcher.subprocess.run")
    def test_rejects_unsafe_job_id_before_writes(self, run) -> None:
        run.return_value = self._git_result()
        with self.assertRaisesRegex(ValueError, "unsafe job id"):
            enqueue_jobs(
                [self._job(job_id="../escape")],
                self.agent_root,
                self.repo,
                self.base_commit,
            )
        self.assertEqual(list((self.agent_root / "queue").iterdir()), [])

    @patch("sosog.orchestration.dispatcher.subprocess.run")
    def test_rejects_path_traversal_before_writes(self, run) -> None:
        run.return_value = self._git_result()
        jobs = [self._job(), self._job(job_id="second", prompt_path="nested/../prompt.md")]
        with self.assertRaisesRegex(ValueError, "unsafe job artifact path"):
            enqueue_jobs(jobs, self.agent_root, self.repo, self.base_commit)
        self.assertEqual(list((self.agent_root / "prompts").iterdir()), [])

    @patch("sosog.orchestration.dispatcher.subprocess.run")
    def test_detects_hash_mismatch_before_writes(self, run) -> None:
        run.return_value = self._git_result()
        with self.assertRaisesRegex(ValueError, "prompt hash mismatch"):
            enqueue_jobs(
                [self._job(prompt_sha256="0" * 64)],
                self.agent_root,
                self.repo,
                self.base_commit,
            )
        self.assertEqual(list((self.agent_root / "manifests").iterdir()), [])

    @patch("sosog.orchestration.dispatcher.shutil.chown")
    @patch("sosog.orchestration.dispatcher.subprocess.run")
    def test_writes_expected_queue_and_starts_unit(self, run, chown) -> None:
        run.side_effect = [self._git_result(), unittest.mock.Mock()]
        enqueue_jobs([self._job()], self.agent_root, self.repo, self.base_commit)
        queue = (self.agent_root / "queue" / "safe-job.job").read_text(encoding="utf-8")
        self.assertEqual(
            queue,
            f"JOB_ID=safe-job\n"
            f"PROMPT_FILE={self.agent_root}/prompts/safe-job.md\n"
            f"JOB_MANIFEST={self.agent_root}/manifests/safe-job.json\n"
            f"JOB_DIR={self.agent_root}/jobs/safe-job\n"
            f"WORKTREE_DIR={self.agent_root}/worktrees/safe-job\n"
            f"BASE_REF={self.base_commit}\n"
            "SANDBOX=workspace-write\n",
        )
        run.assert_called_with(
            ["systemctl", "start", "codex-agent@safe-job.service"], check=True
        )
        self.assertTrue(chown.called)

    @patch("sosog.orchestration.dispatcher.shutil.chown")
    @patch("sosog.orchestration.dispatcher.subprocess.run")
    def test_dynamic_job_freezes_canonical_evidence_without_start(self, run, chown):
        run.return_value = self._git_result()
        enqueue_dynamic_job("dynamic", "repair\n", self._manifest(), self.agent_root,
                            self.repo, self.base_commit, start_worker=False)
        prompt = self.agent_root / "prompts" / "dynamic.md"
        manifest = self.agent_root / "manifests" / "dynamic.json"
        queue = self.agent_root / "queue" / "dynamic.job"
        self.assertEqual(prompt.read_bytes(), b"repair\n")
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
        frozen_manifest = json.loads(manifest.read_text())
        self.assertEqual(frozen_manifest["job_id"], "dynamic")
        self.assertEqual(hashlib.sha256(prompt.read_bytes()).hexdigest(),
                         hashlib.sha256(b"repair\n").hexdigest())
        self.assertIn("SANDBOX=workspace-write\n", queue.read_text())
        self.assertEqual(run.call_count, 1)
        self.assertEqual(len(list((self.agent_root / "queue").glob(".*"))), 0)

    @patch("sosog.orchestration.dispatcher.subprocess.run")
    def test_dynamic_denial_and_bad_manifest_write_nothing(self, run):
        run.return_value = self._git_result()
        bad = self._manifest(); bad["permissions"]["network_access"] = True
        with self.assertRaises(PermissionError):
            enqueue_dynamic_job("dynamic", "repair", bad, self.agent_root,
                                self.repo, self.base_commit)
        self.assertFalse(any(any((self.agent_root / name).iterdir())
                             for name in ("prompts", "manifests", "queue")))

    @patch("sosog.orchestration.dispatcher.subprocess.run")
    def test_dynamic_manifest_job_id_and_bounds_validate_before_write(self, run):
        run.return_value = self._git_result()
        bad = self._manifest("wrong"); bad["max_diff_bytes"] = 0
        with self.assertRaises(ValueError):
            enqueue_dynamic_job("dynamic", "repair", bad, self.agent_root,
                                self.repo, self.base_commit)
        self.assertEqual(list((self.agent_root / "queue").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
