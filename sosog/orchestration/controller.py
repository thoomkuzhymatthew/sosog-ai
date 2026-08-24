"""Repair-controller interface for orchestrated Codex workers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class ControllerResult:
    """Terminal result and frozen output location for a repair attempt."""

    status: str
    frozen_directory: Path | None = None
    detail: str | None = None


def run_repair_controller(
    job_id: str,
    agent_root: str | Path,
    repo_root: str | Path,
    vertical_adapter: Any,
    allowed_changed_paths: Sequence[str],
) -> ControllerResult:
    """Run and supervise one isolated repair worker.

    The eventual implementation will replace
    ``scripts/run_airline_flight_change_repair_controller.sh``: start the
    worker, poll ``agent_root/jobs/<job_id>/status`` until success, failure,
    or timeout, require the latest worker circuit breaker to have passed,
    freeze only manifest-allowed changed files into an isolated directory,
    and retain the worker trace for evaluation by the vertical adapter.
    Component 4 will supply the implementation once it can call this API.
    """

    raise NotImplementedError("the component 4 repair controller is not implemented")
