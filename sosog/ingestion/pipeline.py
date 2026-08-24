"""Raw-export to durable normalized episode orchestration."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from sosog.ingestion.adapters.generic_mapped import normalize
from sosog.ingestion.schema import NormalizedEpisode


def _put_immutable(source: Path, artifact_dir: Path) -> tuple[dict[str, str], bytes]:
    body = source.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    suffix = source.suffix.lower() or ".bin"
    destination = artifact_dir / "sha256" / digest[:2] / f"{digest}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != body:
            raise RuntimeError(f"content-address collision at {destination}")
    else:
        temporary_name = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
                temporary_name = temporary.name
                temporary.write(body)
                temporary.flush()
                os.fsync(temporary.fileno())
            try:
                os.link(temporary_name, destination)
            except FileExistsError:
                if destination.read_bytes() != body:
                    raise RuntimeError(f"content-address collision at {destination}")
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
    return {"uri": destination.resolve().as_uri(), "sha256": digest}, body


def _records(source: Path, body: bytes, mapping: dict[str, Any]) -> Iterable[dict[str, Any]]:
    input_format = mapping.get("input_format") or source.suffix.lower().lstrip(".")
    text = body.decode(mapping.get("encoding", "utf-8"))
    if input_format == "jsonl":
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    elif input_format == "csv":
        values = list(csv.DictReader(io.StringIO(text)))
    elif input_format == "json":
        payload = json.loads(text)
        records_path = mapping.get("records_path")
        if records_path:
            for part in records_path.split("."):
                payload = payload[int(part)] if isinstance(payload, list) else payload[part]
        values = payload if isinstance(payload, list) else [payload]
    else:
        raise ValueError(f"unsupported input_format: {input_format!r}")
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ValueError(f"raw record {index} must be an object")
        yield value


def _validate(episode: NormalizedEpisode) -> None:
    missing = []
    if not episode.episode_id:
        missing.append("episode_id")
    if not episode.source_trace_id:
        missing.append("source_trace_id")
    if not episode.outcome.status:
        missing.append("outcome.status")
    if episode.started_at in (None, ""):
        missing.append("started_at")
    if episode.completed_at in (None, ""):
        missing.append("completed_at")
    if not isinstance(episode.calls, list):
        missing.append("calls")
    if missing:
        raise ValueError(f"normalized episode missing required fields: {missing}")


def ingest_file(
    raw_export: str | Path,
    mapping: dict[str, Any],
    *,
    store: Any,
    artifact_dir: str | Path,
) -> list[NormalizedEpisode]:
    """Archive first, then normalize, validate, and persist every raw record."""
    source = Path(raw_export)
    raw_ref, body = _put_immutable(source, Path(artifact_dir))
    episodes = []
    for index, raw in enumerate(_records(source, body, mapping)):
        try:
            episode = replace(normalize(raw, mapping), raw_ref=raw_ref)
            _validate(episode)
            episodes.append(episode)
        except Exception as exc:
            raise ValueError(f"raw record {index} rejected: {exc}") from exc
    for index, episode in enumerate(episodes):
        try:
            if not store.record_episode(episode.to_store_record()):
                raise RuntimeError("store rejected episode")
        except Exception as exc:
            raise ValueError(
                f"normalized episode {index} persistence failed: {exc}"
            ) from exc
    return episodes
