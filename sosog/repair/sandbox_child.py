"""Trusted child-side protocol for one isolated candidate execution.

This file is copied into a minimal read-only Bubblewrap root.  It must never
contain evaluator fixtures, expected answers, credentials, or repository
paths.  The untrusted candidate receives only one intent and a tool RPC proxy.
"""

from __future__ import annotations

import importlib.util
import json
import resource
import sys
from typing import Any


_MAX_FRAME_BYTES = 1_048_576
_FAILURE_CODES = frozenset(
    {
        "candidate_import_failed",
        "candidate_entry_point_invalid",
        "candidate_execution_failed",
        "candidate_result_invalid",
        "candidate_result_serialization_failed",
    }
)


def _receive() -> dict[str, Any]:
    raw = sys.stdin.buffer.readline(_MAX_FRAME_BYTES + 1)
    if not raw or len(raw) > _MAX_FRAME_BYTES or not raw.endswith(b"\n"):
        raise RuntimeError("invalid evaluator protocol input")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("evaluator protocol frame must be an object")
    return value


_protocol_output = sys.stdout.buffer


def _send(value: dict[str, Any]) -> None:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8") + b"\n"
    if len(raw) > _MAX_FRAME_BYTES:
        raise RuntimeError("evaluator protocol output is too large")
    _protocol_output.write(raw)
    _protocol_output.flush()


def _fail(code: str) -> int:
    """Return a stable failure category without serializing exception payloads."""
    if code not in _FAILURE_CODES:
        code = "candidate_execution_failed"
    _send({"type": "failure", "code": code})
    return 1


class _ToolProxy:
    """Candidate-facing capability object with no evaluator state attached."""

    __slots__ = ()

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        _send({"type": "tool_call", "name": name, "arguments": arguments})
        response = _receive()
        if response.get("type") != "tool_result" or type(response.get("ok")) is not bool:
            raise RuntimeError("invalid evaluator tool response")
        if not response["ok"]:
            raise RuntimeError("tool call was rejected")
        return response.get("value")


def _set_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))


def main() -> int:
    # Candidate print output is discarded by the parent and can never corrupt
    # the line protocol held in _protocol_output.
    sys.stdout = sys.stderr
    _set_limits()
    start = _receive()
    if set(start) != {"type", "intent"} or start.get("type") != "start":
        raise RuntimeError("invalid evaluator start frame")

    # Isolated mode deliberately omits the script directory from sys.path.
    # Add only the minimal read-only sandbox package, never the host repo.
    sys.path.insert(0, "/sandbox")
    try:
        from crystallized.airline.contracts import ExecutionResult
    except BaseException:
        return _fail("candidate_import_failed")

    spec = importlib.util.spec_from_file_location(
        "crystallized.airline.flight_change", "/sandbox/candidate.py"
    )
    if spec is None or spec.loader is None:
        return _fail("candidate_import_failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        return _fail("candidate_import_failed")
    execute = getattr(module, "execute", None)
    if not callable(execute):
        return _fail("candidate_entry_point_invalid")
    try:
        result = execute(start["intent"], _ToolProxy())
    except BaseException:
        return _fail("candidate_execution_failed")
    if not isinstance(result, ExecutionResult):
        return _fail("candidate_result_invalid")
    try:
        _send(
            {
                "type": "result",
                "status": result.status.value,
                "reason": result.reason,
                "writes_executed": result.writes_executed,
                "model_calls": result.model_calls,
                "details": result.details,
            }
        )
    except BaseException:
        return _fail("candidate_result_serialization_failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
