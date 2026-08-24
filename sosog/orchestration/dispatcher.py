"""Validate, freeze, enqueue, and start Codex worker jobs."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ARTIFACT_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _relative_path(value: Any) -> Path:
    if (
        not isinstance(value, str)
        or value.startswith("/")
        or ".." in value
        or not _ARTIFACT_PATH.fullmatch(value)
    ):
        raise ValueError(f"unsafe job artifact path: {value}")
    return Path(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def enqueue_jobs(
    jobs: Iterable[Mapping[str, Any]],
    agent_root: str | os.PathLike[str],
    repo: str | os.PathLike[str],
    base_commit: str,
) -> None:
    """Validate, freeze, enqueue, and start an arbitrary set of Codex jobs.

    Job mappings use the family launcher's reviewed-source fields:
    ``job_id``, ``prompt_path``, ``prompt_sha256``, ``manifest_path``, and
    ``manifest_sha256``. All specs and hashes are validated before any file
    is written, so one invalid job cannot partially dispatch the batch.
    """

    if os.geteuid() != 0:
        raise PermissionError("enqueue_jobs must be run as root")

    root = Path(agent_root)
    repository = Path(repo)
    if not isinstance(base_commit, str) or not _FULL_COMMIT.fullmatch(base_commit):
        raise ValueError("base_commit must be a full hexadecimal Git commit")
    resolved = subprocess.run(
        [
            "git",
            "-C",
            os.fspath(repository),
            "rev-parse",
            "--verify",
            f"{base_commit}^{{commit}}",
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    if resolved != base_commit:
        raise ValueError(f"base commit is unavailable in {repository}: {base_commit}")

    validated: list[tuple[str, Path, Path]] = []
    seen_ids: set[str] = set()
    for job in jobs:
        if not isinstance(job, Mapping):
            raise ValueError("each job must be a mapping")
        job_id = job.get("job_id")
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise ValueError(f"unsafe job id: {job_id}")
        if job_id in seen_ids:
            raise ValueError(f"duplicate job id: {job_id}")
        seen_ids.add(job_id)

        prompt_source = repository / _relative_path(job.get("prompt_path"))
        manifest_source = repository / _relative_path(job.get("manifest_path"))
        if _sha256(prompt_source) != job.get("prompt_sha256"):
            raise ValueError(f"prompt hash mismatch: {job_id}")
        if _sha256(manifest_source) != job.get("manifest_sha256"):
            raise ValueError(f"manifest hash mismatch: {job_id}")
        validated.append((job_id, prompt_source, manifest_source))

    for job_id, prompt_source, manifest_source in validated:
        prompt_target = root / "prompts" / f"{job_id}.md"
        manifest_target = root / "manifests" / f"{job_id}.json"
        queue_target = root / "queue" / f"{job_id}.job"
        shutil.copyfile(prompt_source, prompt_target)
        shutil.copyfile(manifest_source, manifest_target)
        for target in (prompt_target, manifest_target):
            target.chmod(0o600)
            shutil.chown(target, user="ubuntu", group="ubuntu")

        queue_text = (
            f"JOB_ID={job_id}\n"
            f"PROMPT_FILE={prompt_target}\n"
            f"JOB_MANIFEST={manifest_target}\n"
            f"JOB_DIR={root}/jobs/{job_id}\n"
            f"WORKTREE_DIR={root}/worktrees/{job_id}\n"
            f"BASE_REF={base_commit}\n"
            "SANDBOX=workspace-write\n"
        )
        fd, temporary_name = tempfile.mkstemp(prefix=f"{job_id}.job.", dir=root / "queue")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(queue_text)
            temporary.chmod(0o600)
            shutil.chown(temporary, user="ubuntu", group="ubuntu")
            os.replace(temporary, queue_target)
        finally:
            temporary.unlink(missing_ok=True)

    for job_id, _, _ in validated:
        subprocess.run(
            ["systemctl", "start", f"codex-agent@{job_id}.service"], check=True
        )
