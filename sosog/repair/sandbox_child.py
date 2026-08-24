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
    from crystallized.airline.contracts import ExecutionResult

    spec = importlib.util.spec_from_file_location(
        "isolated_candidate", "/sandbox/candidate.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("candidate loader is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    execute = getattr(module, "execute", None)
    if not callable(execute):
        raise RuntimeError("candidate entry point is unavailable")
    result = execute(start["intent"], _ToolProxy())
    if not isinstance(result, ExecutionResult):
        raise RuntimeError("candidate returned an invalid result")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
