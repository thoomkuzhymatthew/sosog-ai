from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sosog.orchestration.dispatcher import enqueue_jobs


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


if __name__ == "__main__":
    unittest.main()
