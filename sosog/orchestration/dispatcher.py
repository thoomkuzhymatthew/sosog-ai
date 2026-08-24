"""Validate, freeze, enqueue, and optionally start Codex worker jobs."""
from __future__ import annotations

import hashlib, json, os, re, shutil, stat, subprocess, tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ARTIFACT_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MANIFEST_KEYS = {"schema_version", "job_id", "allowed_changed_paths", "max_changed_files", "max_diff_bytes", "require_changes", "permissions"}
_PERMISSION_KEYS = {"may_commit", "may_merge", "may_push", "may_deploy", "network_access"}

def _relative_path(value: Any) -> Path:
    if (not isinstance(value, str) or not value or value.startswith("/")
            or ".." in Path(value).parts or Path(value) == Path(".")
            or not _ARTIFACT_PATH.fullmatch(value)):
        raise ValueError(f"unsafe job artifact path: {value}")
    return Path(value)

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _validate_environment(agent_root: str | os.PathLike[str], repo: str | os.PathLike[str], base_commit: str) -> tuple[Path, Path]:
    if os.geteuid() != 0:
        raise PermissionError("enqueue_jobs must be run as root")
    root, repository = Path(agent_root), Path(repo)
    if not root.is_absolute() or not repository.is_absolute():
        raise ValueError("agent_root and repo must be absolute paths")
    if not isinstance(base_commit, str) or not _FULL_COMMIT.fullmatch(base_commit):
        raise ValueError("base_commit must be a full hexadecimal Git commit")
    resolved = subprocess.run(["git", "-C", os.fspath(repository), "rev-parse", "--verify", f"{base_commit}^{{commit}}"], check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
    if resolved != base_commit:
        raise ValueError(f"base commit is unavailable in {repository}: {base_commit}")
    for name in ("prompts", "manifests", "queue"):
        path = root / name
        try: info = path.lstat()
        except OSError as exc: raise ValueError(f"required agent directory is unavailable: {path}") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"required agent path must be a non-symlink directory: {path}")
    return root, repository

def _validate_job_id(job_id: Any) -> str:
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id): raise ValueError(f"unsafe job id: {job_id}")
    return job_id

def _validate_manifest(manifest: Any, job_id: str) -> dict[str, Any]:
    if not isinstance(manifest, Mapping): raise ValueError("manifest must be a mapping")
    value = dict(manifest)
    if set(value) != _MANIFEST_KEYS or value.get("schema_version") != 2: raise ValueError("manifest has unsupported fields or schema version")
    if value.get("job_id") != job_id: raise ValueError("manifest job ID does not match job")
    paths = value.get("allowed_changed_paths")
    if not isinstance(paths, (list, tuple)) or not paths: raise ValueError("manifest requires allowed changed paths")
    normalized = [_relative_path(path).as_posix() for path in paths]
    if len(normalized) != len(set(normalized)): raise ValueError("manifest allowed paths must be unique")
    for name in ("max_changed_files", "max_diff_bytes"):
        if type(value.get(name)) is not int or value[name] < 1: raise ValueError(f"manifest {name} must be a positive integer")
    if value["max_changed_files"] > len(normalized): raise ValueError("max_changed_files exceeds allowed path count")
    if value.get("require_changes") is not True: raise ValueError("dynamic manifest must require changes")
    permissions = value.get("permissions")
    if not isinstance(permissions, Mapping) or set(permissions) != _PERMISSION_KEYS: raise ValueError("manifest permissions are incomplete")
    if any(permissions.get(key) is not False for key in _PERMISSION_KEYS): raise PermissionError("network, commit, merge, push, and deploy are denied")
    value["allowed_changed_paths"], value["permissions"] = normalized, dict(permissions)
    return value

def _queue_text(root: Path, job_id: str, base_commit: str) -> str:
    return f"JOB_ID={job_id}\nPROMPT_FILE={root}/prompts/{job_id}.md\nJOB_MANIFEST={root}/manifests/{job_id}.json\nJOB_DIR={root}/jobs/{job_id}\nWORKTREE_DIR={root}/worktrees/{job_id}\nBASE_REF={base_commit}\nSANDBOX=workspace-write\n"

def _install_bytes(data: bytes, target: Path) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent); temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
        temporary.chmod(0o600); shutil.chown(temporary, user="ubuntu", group="ubuntu")
        # Publishing with a hard link gives us O_EXCL semantics: immutable job
        # evidence can never be silently replaced by a concurrent dispatcher.
        os.link(temporary, target, follow_symlinks=False)
    finally: temporary.unlink(missing_ok=True)

def _freeze(root: Path, job_id: str, base_commit: str, prompt: bytes, manifest: bytes) -> None:
    targets = ((root/"prompts"/f"{job_id}.md", prompt), (root/"manifests"/f"{job_id}.json", manifest), (root/"queue"/f"{job_id}.job", _queue_text(root, job_id, base_commit).encode()))
    if any(path.exists() or path.is_symlink() for path, _ in targets): raise FileExistsError(f"job evidence already exists: {job_id}")
    installed: list[Path] = []
    try:
        for path, data in targets: _install_bytes(data, path); installed.append(path)
    except Exception:
        for path in installed: path.unlink(missing_ok=True)
        raise

def _start(job_ids: Sequence[str]) -> None:
    for job_id in job_ids: subprocess.run(["systemctl", "start", f"codex-agent@{job_id}.service"], check=True)

def enqueue_jobs(jobs: Iterable[Mapping[str, Any]], agent_root: str | os.PathLike[str], repo: str | os.PathLike[str], base_commit: str, *, start_workers: bool = True) -> None:
    """Dispatch reviewed repository-backed specs; existing callers start by default."""
    root, repository = _validate_environment(agent_root, repo, base_commit); validated = []; seen_ids: set[str] = set()
    for job in jobs:
        if not isinstance(job, Mapping): raise ValueError("each job must be a mapping")
        job_id = _validate_job_id(job.get("job_id"))
        if job_id in seen_ids: raise ValueError(f"duplicate job id: {job_id}")
        seen_ids.add(job_id); prompt_source = repository/_relative_path(job.get("prompt_path")); manifest_source = repository/_relative_path(job.get("manifest_path"))
        if _sha256(prompt_source) != job.get("prompt_sha256"): raise ValueError(f"prompt hash mismatch: {job_id}")
        if _sha256(manifest_source) != job.get("manifest_sha256"): raise ValueError(f"manifest hash mismatch: {job_id}")
        validated.append((job_id, prompt_source.read_bytes(), manifest_source.read_bytes()))
    for job_id, prompt, manifest in validated: _freeze(root, job_id, base_commit, prompt, manifest)
    if start_workers: _start([item[0] for item in validated])

def enqueue_dynamic_job(job_id: str, prompt: str, manifest: Mapping[str, Any], agent_root: str | os.PathLike[str], repo: str | os.PathLike[str], base_commit: str, *, start_worker: bool = True) -> None:
    """Validate and atomically publish one in-memory, hard-denied coding job."""
    root, _ = _validate_environment(agent_root, repo, base_commit); safe_id = _validate_job_id(job_id)
    if not isinstance(prompt, str) or not prompt.strip() or "\x00" in prompt: raise ValueError("prompt must be non-empty text without NUL bytes")
    prompt_bytes = prompt.encode("utf-8")
    if len(prompt_bytes) > 1024*1024: raise ValueError("prompt exceeds one MiB")
    safe_manifest = _validate_manifest(manifest, safe_id)
    manifest_bytes = (json.dumps(safe_manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)+"\n").encode()
    _freeze(root, safe_id, base_commit, prompt_bytes, manifest_bytes)
    if start_worker: _start([safe_id])
