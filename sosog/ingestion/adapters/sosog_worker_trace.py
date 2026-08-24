"""Normalize one SOSOG Codex-worker attempt into a product episode."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections import Counter
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from sosog.ingestion.pipeline import archive_raw_file
from sosog.ingestion.redaction import redact_record
from sosog.ingestion.schema import Cost, NormalizedEpisode, Outcome


_TEST_COMMAND = re.compile(
    r"(?:^|[ /])(pytest|unittest|tox|npm test|pnpm test|yarn test|cargo test|go test)(?:$|[ ;])",
    re.IGNORECASE,
)
_INSPECTION_COMMAND = re.compile(
    r"(?:^|[ /])(cat|find|git (?:diff|status|show)|grep|head|ls|rg|sed|tail)(?:$|[ ;])",
    re.IGNORECASE,
)
_SUCCESS_STATUSES = {"succeeded", "success", "passed"}
_DEFAULT_REDACTION: dict[str, Any] = {"mode": "tokenize"}


def _events(raw: bytes | str | Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        values = []
        for line_number, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"worker trace line {line_number} is invalid JSON") from exc
            if not isinstance(value, dict):
                raise ValueError(f"worker trace line {line_number} must be an object")
            values.append(value)
        return values
    return [dict(value) for value in raw]


def _single(events: list[dict[str, Any]], event_type: str) -> dict[str, Any]:
    matches = [event for event in events if event.get("type") == event_type]
    if len(matches) != 1:
        raise ValueError(f"worker trace requires exactly one {event_type!r} event")
    return matches[0]


def _relative_path(path: Any, worktree: str | None) -> str:
    rendered = str(path or "")
    if not rendered:
        return "unknown"
    if worktree:
        prefix = worktree.rstrip("/") + "/"
        if rendered.startswith(prefix):
            return rendered[len(prefix) :]
    value = PurePosixPath(rendered)
    return value.name or "unknown"


def _path_token(path: str) -> str:
    return f"[REDACTED:{hashlib.sha256(path.encode()).hexdigest()[:12]}]"


def _command_category(command: Any) -> str:
    rendered = str(command or "")
    if _TEST_COMMAND.search(rendered):
        return "run_tests"
    if _INSPECTION_COMMAND.search(rendered):
        return "inspect_workspace"
    return "run_command"


def _program(command: Any) -> str:
    try:
        parts = shlex.split(str(command or ""))
    except ValueError:
        return "unknown"
    if not parts:
        return "unknown"
    program = PurePosixPath(parts[0]).name
    return program if program not in {"bash", "sh"} else "shell"


def _calls(
    events: list[dict[str, Any]], worktree: str | None, redaction: Mapping[str, Any] | None
) -> tuple[list[dict[str, Any]], int, int]:
    command_counts: Counter[tuple[str, str, bool]] = Counter()
    changes: set[tuple[str, str, str]] = set()
    reported = False
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "command_execution":
            failed = item.get("exit_code") not in (0, "0")
            command_counts[
                (
                    _command_category(item.get("command")),
                    _program(item.get("command")),
                    failed,
                )
            ] += 1
        elif item_type == "file_change":
            for change in item.get("changes") or []:
                if isinstance(change, dict):
                    relative_path = _relative_path(change.get("path"), worktree)
                    changes.add(
                        (
                            _path_token(relative_path),
                            str(change.get("kind") or "unknown"),
                            PurePosixPath(relative_path).suffix or "none",
                        )
                    )
        elif item_type == "agent_message":
            reported = True

    calls: list[dict[str, Any]] = []
    for (category, program, failed), count in sorted(command_counts.items()):
        calls.append(
            {
                "name": category,
                "arguments": {"program": program, "count": count, "failed": failed},
                "is_write": False,
                "result": None,
            }
        )
    if changes:
        paths = [path for path, _, _ in sorted(changes)]
        calls.append(
            {
                "name": "edit_files",
                "arguments": {
                    "paths": paths,
                    "kinds": [kind for _, kind, _ in sorted(changes)],
                    "extensions": sorted(
                        {extension for _, _, extension in changes}
                    ),
                },
                "is_write": True,
                "result": {"changed_file_count": len(paths)},
            }
        )
    if reported:
        calls.append(
            {
                "name": "report_result",
                "arguments": {},
                "is_write": False,
                "result": None,
            }
        )

    protected = ("calls.*.name", "calls.*.is_write")
    sanitized = redact_record(
        {"calls": calls}, redaction or _DEFAULT_REDACTION, protected_paths=protected
    )["calls"]
    for call in sanitized:
        arguments = json.dumps(
            call["arguments"],
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        call["signature"] = f"{call['name']}({arguments})"
    return sanitized, sum(command_counts.values()), len(changes)


def normalize_worker_trace(
    raw: bytes | str | Iterable[Mapping[str, Any]],
    *,
    raw_ref: Mapping[str, str] | None = None,
    redaction: Mapping[str, Any] | None = None,
) -> NormalizedEpisode:
    """Map a complete worker trace without retaining commands, output, or prose."""
    events = _events(raw)
    started = _single(events, "sosog.job.started")
    finished = _single(events, "sosog.job.finished")
    job_id = str(started.get("job_id") or "").strip()
    attempt = str(started.get("attempt") or "").strip()
    if not job_id or not attempt:
        raise ValueError("worker trace start event requires job_id and attempt")
    if finished.get("job_id") != job_id or str(finished.get("attempt")) != attempt:
        raise ValueError("worker trace start and finish events identify different attempts")

    git = started.get("git") if isinstance(started.get("git"), dict) else {}
    calls, command_count, changed_file_count = _calls(events, git.get("worktree"), redaction)
    usage = finished.get("usage_events") or []
    tokens_in = sum(
        int(item.get("input_tokens") or 0)
        for item in usage
        if isinstance(item, dict)
    )
    tokens_out = sum(
        int(item.get("output_tokens") or 0)
        for item in usage
        if isinstance(item, dict)
    )
    final_status = str(finished.get("status") or "unknown").strip().lower()
    exit_status = finished.get("exit_status")
    succeeded = final_status in _SUCCESS_STATUSES and exit_status in (0, "0")
    digest = (raw_ref or {}).get("sha256") or hashlib.sha256(
        json.dumps(events, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    source_trace_id = f"{job_id}:{attempt}:{digest[:16]}"
    return NormalizedEpisode(
        episode_id="worker-" + hashlib.sha256(source_trace_id.encode()).hexdigest()[:24],
        task_type_id=None,
        source_trace_id=source_trace_id,
        started_at=started.get("timestamp"),
        completed_at=finished.get("timestamp"),
        calls=calls,
        outcome=Outcome(
            status="COMPLETE",
            success=succeeded,
            success_source="programmatic_verifier",
            confidence=1.0,
        ),
        cost=Cost(
            tokens_in=tokens_in or None,
            tokens_out=tokens_out or None,
            model="codex",
        ),
        annotations={
            "vertical": "sosog_internal",
            "initial_request": f"Execute SOSOG worker job: {job_id}",
            "job_id": job_id,
            "attempt": attempt,
            "worker": started.get("worker"),
            "sandbox": started.get("sandbox"),
            "base_commit": git.get("base_commit"),
            "final_status": final_status,
            "exit_status": exit_status,
            "command_count": command_count,
            "changed_file_count": changed_file_count,
        },
        raw_ref=dict(raw_ref or {}),
    )


def ingest_worker_trace(
    trace_path: str | Path,
    *,
    store: Any,
    artifact_dir: str | Path,
    redaction: Mapping[str, Any] | None = None,
) -> NormalizedEpisode:
    """Archive, normalize, then persist one complete SOSOG worker trace."""
    raw_ref, body = archive_raw_file(trace_path, artifact_dir)
    episode = normalize_worker_trace(body, raw_ref=raw_ref, redaction=redaction)
    get_episode = getattr(store, "get_episode", None)
    existing = get_episode(episode.episode_id) if get_episode is not None else None
    if existing is not None:
        if (
            existing.get("source_trace_id") != episode.source_trace_id
            or existing.get("raw_artifact_sha256") != episode.raw_ref.get("sha256")
        ):
            raise RuntimeError(
                f"existing worker episode {episode.episode_id} has different evidence"
            )
        return replace(episode, task_type_id=existing.get("task_type_id"))
    if not store.record_episode(episode.to_store_record()):
        raise RuntimeError(f"store rejected worker episode {episode.episode_id}")
    return episode
