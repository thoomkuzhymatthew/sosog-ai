"""Fail-closed process isolation for generated Python repair candidates."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from crystallized.airline import contracts as airline_contracts
from crystallized.airline.contracts import ExecutionResult, ExecutionStatus

from .contracts import CandidateReference


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_CANDIDATE_BYTES = 1_048_576
_MAX_FRAME_BYTES = 1_048_576
_MAX_PROTOCOL_BYTES = 2_097_152


class ToolHandler(Protocol):
    def call(self, name: str, arguments: dict[str, Any]) -> Any: ...


class SandboxUnavailableError(RuntimeError):
    """Raised when the required OS isolation boundary is unavailable."""


class CandidateSandboxError(RuntimeError):
    """A deliberately payload-free candidate execution failure."""


@dataclass(frozen=True)
class VerifiedCandidate:
    digest: str
    source: bytes


@dataclass(frozen=True)
class SandboxConfig:
    bwrap_path: str | os.PathLike[str] | None = None
    python_path: str | os.PathLike[str] = "/usr/bin/python3"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("sandbox timeout must be finite and positive")
        python = Path(self.python_path)
        if not python.is_absolute():
            raise ValueError("sandbox Python path must be absolute")


def verify_candidate(candidate: CandidateReference) -> VerifiedCandidate:
    """Read a regular candidate once through O_NOFOLLOW and verify its digest."""
    if not isinstance(candidate, CandidateReference) or candidate.location is None:
        raise ValueError("candidate location is required")
    path = Path(candidate.location)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("candidate source is unavailable") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("candidate source must be a regular file")
        if info.st_size > _MAX_CANDIDATE_BYTES:
            raise ValueError("candidate source exceeds one MiB")
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            if size > _MAX_CANDIDATE_BYTES:
                raise ValueError("candidate source exceeds one MiB")
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    source = b"".join(chunks)
    digest = hashlib.sha256(source).hexdigest()
    if not _DIGEST.fullmatch(candidate.digest) or digest != candidate.digest:
        raise ValueError("candidate digest mismatch")
    return VerifiedCandidate(digest, source)


def _trusted_executable(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        info = resolved.stat()
    except OSError as exc:
        raise SandboxUnavailableError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or not os.access(resolved, os.X_OK):
        raise SandboxUnavailableError(f"{label} is not executable")
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise SandboxUnavailableError(f"{label} must be root-owned and non-writable")
    return resolved


def discover_bwrap(configured: str | os.PathLike[str] | None = None) -> Path:
    """Find the trusted system or bundled Bubblewrap executable."""
    candidates: list[Path] = []
    if configured is not None:
        candidates.append(Path(configured))
    environment = os.environ.get("SOSOG_EVALUATOR_BWRAP")
    if environment:
        candidates.append(Path(environment))
    system = shutil.which("bwrap")
    if system:
        candidates.append(Path(system))
    codex = Path(
        os.environ.get(
            "CODEX_AGENT_CODEX_BIN", "/opt/sosog/codex-cli/current/bin/codex"
        )
    )
    try:
        package_root = codex.resolve(strict=True).parent.parent
        candidates.append(package_root / "codex-resources" / "bwrap")
    except OSError:
        pass
    for candidate in candidates:
        try:
            return _trusted_executable(candidate, "Bubblewrap")
        except SandboxUnavailableError:
            continue
    raise SandboxUnavailableError("trusted Bubblewrap is unavailable")


def sandbox_available(config: SandboxConfig | None = None) -> bool:
    try:
        value = config or SandboxConfig()
        discover_bwrap(value.bwrap_path)
        _trusted_executable(Path(value.python_path), "sandbox Python")
        return True
    except SandboxUnavailableError:
        return False


def _copy_trusted_file(source: Path, target: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CandidateSandboxError("trusted sandbox input is invalid")
        target.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(descriptor, "rb", closefd=False) as reader:
            with target.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
        target.chmod(0o400)
    finally:
        os.close(descriptor)


def _sandbox_command(root: Path, config: SandboxConfig) -> list[str]:
    bwrap = discover_bwrap(config.bwrap_path)
    python = _trusted_executable(Path(config.python_path), "sandbox Python")
    command = [
        os.fspath(bwrap),
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--cap-drop",
        "ALL",
        "--clearenv",
        "--setenv",
        "HOME",
        "/nonexistent",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind-try",
        "/lib64",
        "/lib64",
        "--dir",
        "/etc",
        "--ro-bind-try",
        "/etc/ld.so.cache",
        "/etc/ld.so.cache",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--ro-bind",
        os.fspath(root),
        "/sandbox",
        "--chdir",
        "/sandbox",
        os.fspath(python),
        "-I",
        "-S",
        "/sandbox/sandbox_child.py",
    ]
    return command


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=2)


def _write_frame(process: subprocess.Popen[bytes], value: dict[str, Any]) -> None:
    if process.stdin is None:
        raise CandidateSandboxError("candidate protocol input is unavailable")
    try:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as exc:
        raise CandidateSandboxError("candidate protocol value is not JSON-safe") from exc
    if len(raw) > _MAX_FRAME_BYTES:
        raise CandidateSandboxError("candidate protocol frame is too large")
    try:
        process.stdin.write(raw)
        process.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        raise CandidateSandboxError("candidate protocol closed unexpectedly") from exc


def _result_from_frame(frame: dict[str, Any]) -> ExecutionResult:
    if set(frame) != {
        "type", "status", "reason", "writes_executed", "model_calls", "details"
    } or frame.get("type") != "result":
        raise CandidateSandboxError("candidate returned an invalid result frame")
    try:
        return ExecutionResult(
            ExecutionStatus(frame["status"]),
            frame["reason"],
            frame["writes_executed"],
            frame["model_calls"],
            frame["details"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CandidateSandboxError("candidate result failed validation") from exc


def run_isolated_candidate(
    candidate: VerifiedCandidate,
    intent: Any,
    tools: ToolHandler,
    *,
    config: SandboxConfig | None = None,
) -> ExecutionResult:
    """Execute one candidate case in a fresh, networkless, read-only namespace."""
    if not isinstance(candidate, VerifiedCandidate):
        raise ValueError("candidate must be verified before sandbox execution")
    settings = config or SandboxConfig()
    child_source = Path(__file__).with_name("sandbox_child.py")
    contracts_source = Path(airline_contracts.__file__ or "")
    with tempfile.TemporaryDirectory(prefix="sosog-evaluator-") as directory:
        root = Path(directory)
        (root / "candidate.py").write_bytes(candidate.source)
        (root / "candidate.py").chmod(0o400)
        _copy_trusted_file(child_source, root / "sandbox_child.py")
        _copy_trusted_file(
            contracts_source, root / "crystallized" / "airline" / "contracts.py"
        )
        for marker in (
            root / "crystallized" / "__init__.py",
            root / "crystallized" / "airline" / "__init__.py",
        ):
            marker.touch(mode=0o400, exist_ok=False)

        process = subprocess.Popen(
            _sandbox_command(root, settings),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + float(settings.timeout_seconds)
        buffer = b""
        total_bytes = 0
        result: ExecutionResult | None = None
        try:
            _write_frame(process, {"type": "start", "intent": intent})
            if process.stdout is None:
                raise CandidateSandboxError("candidate protocol output is unavailable")
            descriptor = process.stdout.fileno()
            while result is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CandidateSandboxError("candidate execution timed out")
                ready, _, _ = select.select([descriptor], [], [], remaining)
                if not ready:
                    raise CandidateSandboxError("candidate execution timed out")
                chunk = os.read(descriptor, 65_536)
                if not chunk:
                    raise CandidateSandboxError("candidate exited without a result")
                total_bytes += len(chunk)
                if total_bytes > _MAX_PROTOCOL_BYTES:
                    raise CandidateSandboxError("candidate protocol output is too large")
                buffer += chunk
                while b"\n" in buffer and result is None:
                    raw, buffer = buffer.split(b"\n", 1)
                    if not raw or len(raw) > _MAX_FRAME_BYTES:
                        raise CandidateSandboxError("candidate protocol frame is invalid")
                    try:
                        frame = json.loads(raw)
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise CandidateSandboxError("candidate protocol frame is invalid") from exc
                    if not isinstance(frame, dict):
                        raise CandidateSandboxError("candidate protocol frame is invalid")
                    if frame.get("type") == "tool_call":
                        if set(frame) != {"type", "name", "arguments"}:
                            raise CandidateSandboxError("candidate tool call is invalid")
                        name, arguments = frame.get("name"), frame.get("arguments")
                        if not isinstance(name, str) or not isinstance(arguments, dict):
                            raise CandidateSandboxError("candidate tool call is invalid")
                        try:
                            value = tools.call(name, arguments)
                            _write_frame(
                                process,
                                {"type": "tool_result", "ok": True, "value": value},
                            )
                        except Exception:
                            _write_frame(
                                process,
                                {"type": "tool_result", "ok": False, "value": None},
                            )
                    elif frame.get("type") == "result":
                        result = _result_from_frame(frame)
                    else:
                        raise CandidateSandboxError("candidate protocol message is invalid")
            remaining = max(0.01, deadline - time.monotonic())
            if process.wait(timeout=remaining) != 0:
                raise CandidateSandboxError("candidate sandbox exited unsuccessfully")
            if buffer.strip():
                raise CandidateSandboxError("candidate emitted trailing protocol output")
            return result
        except subprocess.TimeoutExpired as exc:
            raise CandidateSandboxError("candidate execution timed out") from exc
        finally:
            _terminate(process)
