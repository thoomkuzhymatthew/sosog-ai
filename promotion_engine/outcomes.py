"""Append-only, hash-chained outcomes for generated transformation jobs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

OUTCOME_STAGES = {
    "AGENT_ATTEMPT",
    "INDEPENDENT_HELD_OUT",
    "ADVERSARIAL_DEFERRAL",
    "HUMAN_SAFETY_REVIEW",
    "SHADOW_ECONOMICS",
    "PROMOTION_DECISION",
}
OUTCOME_STATUSES = {"PASSED", "FAILED", "PENDING", "REJECTED", "DEFERRED"}
GENESIS_HASH = "0" * 64


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _record_hash(record: dict[str, Any]) -> str:
    value = {key: item for key, item in record.items() if key != "record_sha256"}
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validate_input(record: dict[str, Any]) -> None:
    if not str(record.get("job_id") or ""):
        raise ValueError("job_id is required")
    if record.get("stage") not in OUTCOME_STAGES:
        raise ValueError(f"unsupported outcome stage: {record.get('stage')}")
    if record.get("status") not in OUTCOME_STATUSES:
        raise ValueError(f"unsupported outcome status: {record.get('status')}")
    if not str(record.get("actor") or ""):
        raise ValueError("actor is required")
    evidence = record.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("evidence must be an object")


def _load_lines(handle: Any, source: str) -> list[dict[str, Any]]:
    handle.seek(0)
    records: list[dict[str, Any]] = []
    previous = GENESIS_HASH
    event_ids: set[str] = set()
    for number, line in enumerate(handle, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{source}:{number}: invalid JSON") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{source}:{number}: record must be an object")
        _validate_input(record)
        if record.get("previous_sha256") != previous:
            raise ValueError(f"{source}:{number}: broken previous hash")
        expected = _record_hash(record)
        if record.get("record_sha256") != expected:
            raise ValueError(f"{source}:{number}: record hash mismatch")
        event_id = str(record.get("event_id") or "")
        if not event_id or event_id in event_ids:
            raise ValueError(f"{source}:{number}: missing or duplicate event_id")
        event_ids.add(event_id)
        previous = expected
        records.append(record)
    return records


def verify_outcome_ledger(path: Path) -> list[dict[str, Any]]:
    """Read and validate every record and link in an outcome ledger."""

    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            return _load_lines(handle, str(path))
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_outcome(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    """Validate and atomically append one hash-linked outcome record."""

    record = dict(value)
    record.setdefault("schema_version", 1)
    record.setdefault("event_id", str(uuid4()))
    record.setdefault("recorded_at", datetime.now(UTC).isoformat())
    _validate_input(record)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            existing = _load_lines(handle, str(path))
            if any(item["event_id"] == record["event_id"] for item in existing):
                raise ValueError(f"duplicate event_id: {record['event_id']}")
            record["previous_sha256"] = (
                existing[-1]["record_sha256"] if existing else GENESIS_HASH
            )
            record["record_sha256"] = _record_hash(record)
            handle.seek(0, os.SEEK_END)
            handle.write(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return record
