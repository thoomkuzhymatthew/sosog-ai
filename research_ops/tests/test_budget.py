from decimal import Decimal

import pytest

from research_ops.budget import BudgetExceeded, BudgetGuard


def test_budget_guard_is_cumulative_and_persistent(tmp_path):
    path = tmp_path / "ledger.json"
    guard = BudgetGuard.create(path, "1.00")
    assert guard.record("0.25", task_id="one") == Decimal("0.25")
    assert guard.record("0.50", task_id="two") == Decimal("0.75")
    assert BudgetGuard.create(path, "1.00").total() == Decimal("0.75")


def test_budget_guard_rejects_event_over_cap_without_mutating(tmp_path):
    guard = BudgetGuard.create(tmp_path / "ledger.json", "1.00")
    guard.record("0.75")
    with pytest.raises(BudgetExceeded):
        guard.record("0.26")
    assert guard.total() == Decimal("0.75")
