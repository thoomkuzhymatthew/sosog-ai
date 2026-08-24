"""Bounded supervisor for one isolated Codex repair worker."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class ControllerResult:
    """Terminal result and frozen output location for a repair attempt."""

    status: str
    frozen_directory: Path | None = None
    detail: str | None = None
    trace_directory: Path | None = None


class SupervisorOperations(Protocol):
    def start(self, unit: str) -> None: ...
    def active_state(self, unit: str) -> str: ...
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class LocalSupervisorOperations:
    """Thin live-system adapter; tests inject a fake instead."""
    def start(self, unit: str) -> None:
        subprocess.run(["systemctl", "start", unit], check=True)

    def active_state(self, unit: str) -> str:
        return subprocess.run(
            ["systemctl", "show", unit, "--property=ActiveState", "--value"],
            check=True, text=True, stdout=subprocess.PIPE,
        ).stdout.strip()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def _safe_relative(value: str) -> Path:
    if not isinstance(value, str):
        raise ValueError("changed path must be a string")
    path = Path(value)
    if (not value or value != value.strip() or path.is_absolute()
            or ".." in path.parts or path == Path(".")):
        raise ValueError(f"unsafe changed path: {value}")
    return path


def _below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _copy_regular_file(source: Path, target: Path) -> None:
    """Copy through a no-follow file descriptor to close the symlink race."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"source is not a regular file: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(descriptor, "rb", closefd=False) as source_handle:
            with target.open("xb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle)
        os.chmod(target, 0o440)
    finally:
        os.close(descriptor)


def _validated_trace_entries(source: Path) -> list[Path]:
    entries = sorted(source.rglob("*"))
    for entry in entries:
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("worker trace must not contain symlinks")
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError(
                "worker trace may contain only directories and regular files"
            )
    return entries


def _copy_trace(source: Path, destination: Path, entries: Sequence[Path]) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for entry in entries:
        relative = entry.relative_to(source)
        info = entry.lstat()
        if stat.S_ISDIR(info.st_mode):
            (destination / relative).mkdir(parents=True, exist_ok=True)
        else:
            _copy_regular_file(entry, destination / relative)


def run_repair_controller(
    job_id: str,
    agent_root: str | Path,
    repo_root: str | Path,
    vertical_adapter: Any,
    allowed_changed_paths: Sequence[str],
    *,
    operations: SupervisorOperations | None = None,
    timeout_seconds: float = 21600.0,
    poll_seconds: float = 10.0,
    frozen_directory: str | Path | None = None,
    start_worker: bool = True,
) -> ControllerResult:
    """Start, bound, validate, and freeze one worker's explicitly allowed files."""
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise ValueError("unsafe job id")
    if timeout_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("timeouts must be positive")
    root = Path(agent_root).resolve(strict=True)
    repo = Path(repo_root).resolve(strict=True)
    if not repo.is_dir():
        raise ValueError("repo root must be a directory")
    worktree_path = root / "worktrees" / job_id
    if worktree_path.is_symlink():
        raise ValueError("worker worktree root must not be a symlink")
    worktree = worktree_path.resolve(strict=True)
    if not _below(worktree, root):
        raise ValueError("worker worktree escapes agent root")
    job_path = root / "jobs" / job_id
    if job_path.is_symlink():
        raise ValueError("worker job directory must not be a symlink")
    job_dir = job_path.resolve(strict=True)
    if not _below(job_dir, root):
        raise ValueError("worker job directory escapes agent root")
    status_file = job_dir / "status"
    allowed = {_safe_relative(item).as_posix() for item in allowed_changed_paths}
    if not allowed:
        raise ValueError("at least one allowed changed path is required")

    ops = operations or LocalSupervisorOperations()
    unit = f"codex-agent@{job_id}.service"
    started = ops.monotonic()
    if start_worker:
        ops.start(unit)
    while True:
        if status_file.is_symlink():
            raise ValueError("worker status must not be a symlink")
        worker_status = status_file.read_text(encoding="utf-8").strip() if status_file.is_file() else "not_started"
        if worker_status == "succeeded":
            break
        if worker_status in {"failed", "circuit_failed"}:
            return ControllerResult("WORKER_FAILED", detail=worker_status)
        if worker_status in {"blocked_auth", "blocked_usage"}:
            return ControllerResult("WORKER_BLOCKED", detail=worker_status)
        if ops.active_state(unit) == "failed":
            return ControllerResult("WORKER_FAILED", detail=worker_status)
        if ops.monotonic() - started >= timeout_seconds:
            return ControllerResult("TIME_LIMIT", detail=worker_status)
        ops.sleep(poll_seconds)

    traces = job_dir / "traces"
    if traces.is_symlink() or not traces.is_dir():
        raise ValueError("worker traces root must be a regular directory")
    trace_dirs = sorted((p for p in traces.iterdir() if p.is_dir() and not p.is_symlink()), key=lambda p: p.name)
    if not trace_dirs:
        raise ValueError("worker produced no trace")
    trace = trace_dirs[-1]
    circuit_path = trace / "circuit-breaker.json"
    changed_path = trace / "changed-files.txt"
    try:
        for evidence in (circuit_path, changed_path):
            evidence_info = evidence.lstat()
            if stat.S_ISLNK(evidence_info.st_mode) or not stat.S_ISREG(evidence_info.st_mode):
                raise ValueError("worker evidence must be regular non-symlink files")
    except OSError as exc:
        raise ValueError("missing worker circuit-breaker or changed-files evidence") from exc
    try:
        circuit = json.loads(circuit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("missing or malformed circuit breaker") from exc
    if not isinstance(circuit, dict) or circuit.get("status") != "passed":
        raise PermissionError("worker circuit breaker did not pass")
    changed = [line.strip() for line in changed_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not changed:
        raise ValueError("worker reported no changed files")
    if len(changed) != len(set(changed)):
        raise ValueError("worker reported duplicate changed files")

    verified: list[tuple[Path, Path]] = []
    for raw in changed:
        relative = _safe_relative(raw)
        if relative.as_posix() not in allowed:
            raise PermissionError(f"changed path is not allowed: {raw}")
        source = worktree / relative
        info = source.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError(f"changed path must be a regular non-symlink file: {raw}")
        resolved = source.resolve(strict=True)
        if not _below(resolved, worktree):
            raise ValueError(f"changed path escapes worktree: {raw}")
        verified.append((relative, resolved))

    destination = (Path(frozen_directory) if frozen_directory is not None
                   else root / "frozen" / job_id).resolve(strict=False)
    if _below(destination, worktree):
        raise ValueError("frozen directory cannot be inside the worker worktree")
    trace_destination = destination.parent / f"{destination.name}-worker-trace"
    if trace_destination.exists() or trace_destination.is_symlink():
        raise FileExistsError(f"trace destination already exists: {trace_destination}")
    trace_entries = _validated_trace_entries(trace)
    destination.mkdir(parents=True, exist_ok=False)
    for relative, source in verified:
        target = destination / relative
        _copy_regular_file(source, target)

    _copy_trace(trace, trace_destination, trace_entries)

    evaluate = getattr(vertical_adapter, "evaluate_frozen", None)
    detail = evaluate(destination, trace_destination) if callable(evaluate) else None
    return ControllerResult(
        "FROZEN_PENDING_EVALUATION",
        destination,
        None if detail is None else str(detail),
        trace_destination,
    )
