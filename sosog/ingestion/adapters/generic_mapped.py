"""A generic field-mapping adapter for JSON-like client trace records."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sosog.ingestion.redaction import redact_record
from sosog.ingestion.schema import Cost, NormalizedEpisode, Outcome


_MISSING = object()
_SUCCESS_SOURCES = {"programmatic_verifier", "client_label"}


def _get(value: Any, path: str | None, default: Any = _MISSING) -> Any:
    if not path:
        if default is _MISSING:
            raise KeyError("empty field path")
        return default
    current = value
    for part in path.split("."):
        if isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        elif default is not _MISSING:
            return default
        else:
            raise KeyError(path)
    return current


def _optional(raw: dict[str, Any], mapping: dict[str, Any], key: str) -> Any:
    return _get(raw, mapping.get(key), None)


def _number(value: Any, kind: type) -> Any:
    if value is None or value == "":
        return None
    return kind(value)


def _success(raw: dict[str, Any], mapping: dict[str, Any]) -> tuple[bool | None, str]:
    path = mapping.get("success_path")
    if not path:
        return None, "unknown"
    try:
        value = _get(raw, path)
    except KeyError:
        return None, "unknown"
    source = mapping.get("success_source")
    if source not in _SUCCESS_SOURCES:
        raise ValueError("success_path requires success_source to be programmatic_verifier or client_label")
    true_values = mapping.get("success_true_values", [True])
    false_values = mapping.get("success_false_values", [False])
    if value in true_values:
        return True, source
    if value in false_values:
        return False, source
    raise ValueError(f"ambiguous success value at {path!r}: {value!r}")


def _calls(raw: dict[str, Any], mapping: dict[str, Any]) -> list[dict[str, Any]]:
    source = _get(raw, mapping.get("calls_path"))
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except json.JSONDecodeError as exc:
            raise ValueError("mapped calls_path string must contain JSON") from exc
    if not isinstance(source, list):
        raise ValueError("mapped calls_path must contain a list")
    write_tools = set(mapping.get("write_tools", []))
    calls = []
    for index, call in enumerate(source):
        if not isinstance(call, dict):
            raise ValueError(f"call {index} must be an object")
        name = _get(call, mapping.get("call_name_key"))
        if not isinstance(name, str) or not name:
            raise ValueError(f"call {index} is missing a non-empty name")
        arguments = _get(call, mapping.get("call_arguments_key"), {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        explicit_write = _get(call, mapping.get("call_is_write_key"), None)
        is_write = name in write_tools if explicit_write is None else bool(explicit_write)
        signature = f"{name}({json.dumps(arguments, sort_keys=True, separators=(',', ':'), default=str)})"
        calls.append({
            "name": name,
            "arguments": arguments,
            "is_write": is_write,
            "result": _get(call, mapping.get("call_result_key"), None),
            "signature": signature,
        })
    return calls


def _protected_redaction_paths(mapping: dict[str, Any]) -> list[str]:
    calls_path = mapping.get("calls_path")
    if not isinstance(calls_path, str) or not calls_path:
        return []
    return [
        f"{calls_path}.*.{relative_path}"
        for key in ("call_name_key", "call_is_write_key")
        if isinstance((relative_path := mapping.get(key)), str) and relative_path
    ]


def normalize(raw_record: dict, mapping: dict) -> NormalizedEpisode:
    """Redact and normalize one record according to the documented mapping keys."""
    raw = redact_record(
        raw_record,
        mapping.get("redaction"),
        protected_paths=_protected_redaction_paths(mapping),
    )
    source_value = _get(raw, mapping.get("source_trace_id_path"))
    if source_value in (None, ""):
        raise ValueError("source_trace_id must not be empty")
    source_trace_id = str(source_value)
    episode_value = _optional(raw, mapping, "episode_id_path")
    episode_id = str(episode_value) if episode_value not in (None, "") else "ep-" + hashlib.sha256(
        source_trace_id.encode("utf-8")
    ).hexdigest()[:24]
    success, success_source = _success(raw, mapping)
    status = _get(raw, mapping.get("status_path"))
    if status in (None, ""):
        raise ValueError("outcome status must not be empty")
    annotations = _optional(raw, mapping, "annotations_path") or {}
    if not isinstance(annotations, dict):
        raise ValueError("mapped annotations_path must contain an object")
    return NormalizedEpisode(
        episode_id=episode_id,
        task_type_id=None,
        source_trace_id=source_trace_id,
        started_at=_get(raw, mapping.get("started_at_path")),
        completed_at=_get(raw, mapping.get("completed_at_path")),
        calls=_calls(raw, mapping),
        outcome=Outcome(
            status=str(status),
            success=success,
            success_source=success_source,
            confidence=_number(_optional(raw, mapping, "confidence_path"), float),
        ),
        cost=Cost(
            usd=_number(_optional(raw, mapping, "cost_usd_path"), float),
            tokens_in=_number(_optional(raw, mapping, "tokens_in_path"), int),
            tokens_out=_number(_optional(raw, mapping, "tokens_out_path"), int),
            model=_optional(raw, mapping, "model_path"),
        ),
        annotations=annotations,
    )
