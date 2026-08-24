"""Configurable PII redaction performed at the ingestion door."""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import re
from typing import Any, Iterable, Mapping


DEFAULT_REDACTION_CONFIG: dict[str, Any] = {
    "mode": "remove",
    "field_name_patterns": [
        "email", "e-mail", "name", "first_name", "last_name", "full_name",
        "phone", "phone_number", "card_number", "credit_card", "cvv", "cvc",
        "ssn", "social_security_number", "password", "secret",
    ],
    "field_paths": [],
}


def _path_matches(path: tuple[str, ...], configured: str) -> bool:
    configured_parts = configured.lower().split(".")
    return len(path) == len(configured_parts) and all(
        fnmatch.fnmatchcase(actual.lower(), pattern)
        for actual, pattern in zip(path, configured_parts)
    )


def _matches(path: tuple[str, ...], patterns: list[str], paths: list[str]) -> bool:
    key = path[-1].lower() if path else ""
    return any(fnmatch.fnmatch(key, pattern.lower()) for pattern in patterns) or any(
        _path_matches(path, configured) for configured in paths
    )


def _replacement(value: Any, mode: str) -> str:
    if mode == "tokenize":
        rendered = repr(value).encode("utf-8")
        return f"[REDACTED:{hashlib.sha256(rendered).hexdigest()[:12]}]"
    return "[REDACTED]"


def redact_record(
    record: Mapping[str, Any],
    config: Mapping[str, Any] | None = None,
    *,
    protected_paths: Iterable[str] = (),
) -> dict[str, Any]:
    """Return a deep redacted copy while preserving mapped structural fields."""
    supplied = dict(config or {})
    patterns = list(DEFAULT_REDACTION_CONFIG["field_name_patterns"])
    if supplied.get("use_defaults", True):
        patterns.extend(supplied.get("field_name_patterns", []))
    else:
        patterns = list(supplied.get("field_name_patterns", []))
    paths = list(supplied.get("field_paths", []))
    mode = supplied.get("mode", DEFAULT_REDACTION_CONFIG["mode"])
    if mode not in {"remove", "tokenize"}:
        raise ValueError("redaction mode must be 'remove' or 'tokenize'")
    regexes = [re.compile(value, re.IGNORECASE) for value in supplied.get("field_name_regexes", [])]
    protected = list(protected_paths)

    def walk(value: Any, path: tuple[str, ...]) -> Any:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                child_path = path + (str(key),)
                is_protected = any(
                    _path_matches(child_path, configured) for configured in protected
                )
                if is_protected:
                    result[key] = copy.deepcopy(item)
                elif _matches(child_path, patterns, paths) or any(r.search(str(key)) for r in regexes):
                    result[key] = _replacement(item, mode)
                else:
                    result[key] = walk(item, child_path)
            return result
        if isinstance(value, list):
            return [walk(item, path + (str(index),)) for index, item in enumerate(value)]
        return copy.deepcopy(value)

    return walk(dict(record), ())
