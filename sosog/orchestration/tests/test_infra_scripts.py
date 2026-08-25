from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[3]
BOOTSTRAP = REPOSITORY / "infra/aws/bootstrap_codex_agents.sh"
UPDATER = REPOSITORY / "infra/aws/update_codex_repo_from_bundle.sh"


def run(*arguments: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class InfraScriptTests(unittest.TestCase):
    def test_bootstrap_installs_every_auth_refresh_asset(self):
        source = BOOTSTRAP.read_text()
        for name in (
            "refresh_codex_auth.sh",
            "codex_login_and_resume.sh",
            "sosog-codex-auth-refresh.service",
            "sosog-codex-auth-refresh.timer",
        ):
            self.assertIn(name, source)
        self.assertIn("systemctl enable sosog-codex-auth-refresh.timer", source)
        run("bash", "-n", str(BOOTSTRAP), cwd=REPOSITORY)
        run("bash", "-n", str(UPDATER), cwd=REPOSITORY)

    def test_bundle_updater_requires_clean_fast_forward_and_preserves_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            run("git", "init", "-b", "main", cwd=source)
            run("git", "config", "user.name", "SOSOG test", cwd=source)
            run("git", "config", "user.email", "test@sosog.invalid", cwd=source)
            tracked = source / "tracked.txt"
            tracked.write_text("base\n")
            run("git", "add", "tracked.txt", cwd=source)
            run("git", "commit", "-m", "base", cwd=source)
            run("git", "clone", str(source), str(target), cwd=root)
            base = run("git", "rev-parse", "HEAD", cwd=source).stdout.strip()
            origin = run("git", "remote", "get-url", "origin", cwd=target).stdout.strip()

            tracked.write_text("updated\n")
            run("git", "add", "tracked.txt", cwd=source)
            run("git", "commit", "-m", "update", cwd=source)
            expected = run("git", "rev-parse", "HEAD", cwd=source).stdout.strip()
            bundle = root / "update.bundle"
            run(
                "git", "bundle", "create", str(bundle), "main", f"^{base}",
                cwd=source,
            )

            environment = dict(os.environ, CODEX_AGENT_REPO=str(target))
            completed = subprocess.run(
                [str(UPDATER), str(bundle), expected],
                cwd=REPOSITORY,
                env=environment,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertIn(expected, completed.stdout)
            self.assertEqual(
                run("git", "rev-parse", "HEAD", cwd=target).stdout.strip(),
                expected,
            )
            self.assertEqual(
                run("git", "remote", "get-url", "origin", cwd=target).stdout.strip(),
                origin,
            )

            (target / "tracked.txt").write_text("dirty\n")
            rejected = subprocess.run(
                [str(UPDATER), str(bundle), expected],
                cwd=REPOSITORY,
                env=environment,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(rejected.returncode, 3)
            self.assertIn("dirty repository", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
