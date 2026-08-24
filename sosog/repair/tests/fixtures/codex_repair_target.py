"""Intentionally defective target used only by the live Codex bridge dogfood.

The isolated worker is expected to repair this file in its detached worktree;
the repaired proposal is frozen for evaluation and is never merged back here.
"""

from crystallized.airline.contracts import ExecutionResult, ExecutionStatus


def execute(intent, tools):
    """Incorrectly completes every input; the dogfood repair must add gates."""
    return ExecutionResult(
        ExecutionStatus.COMPLETED,
        "intentionally unrepaired dogfood fixture",
        0,
    )
