"""Crash-safe local budget ledger used by each isolated worker."""

from __future__ import annotations

import fcntl
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


class BudgetExceeded(RuntimeError):
    """Raised before a cost event would cross a configured hard cap."""


@dataclass(frozen=True)
class BudgetGuard:
    ledger_path: Path
    track_cap_usd: Decimal

    @classmethod
    def create(cls, ledger_path: Path, track_cap_usd: float | str) -> "BudgetGuard":
        return cls(ledger_path=ledger_path, track_cap_usd=Decimal(str(track_cap_usd)))

    def _read(self, handle: Any) -> dict[str, Any]:
        handle.seek(0)
        raw = handle.read()
        if not raw.strip():
            return {"schema_version": 1, "total_usd": "0", "events": []}
        value = json.loads(raw)
        if not isinstance(value.get("events"), list):
            raise ValueError("budget ledger events must be a list")
        return value

    def total(self) -> Decimal:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            value = self._read(handle)
            return Decimal(str(value.get("total_usd", "0")))

    def record(self, amount_usd: float | str, **details: Any) -> Decimal:
        amount = Decimal(str(amount_usd))
        if amount < 0:
            raise ValueError("budget event amount cannot be negative")
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            value = self._read(handle)
            current = Decimal(str(value.get("total_usd", "0")))
            updated = current + amount
            if updated > self.track_cap_usd:
                raise BudgetExceeded(
                    f"track cap ${self.track_cap_usd} would be exceeded by ${updated}"
                )
            value["total_usd"] = str(updated)
            value["events"].append(
                {"amount_usd": str(amount), "cumulative_usd": str(updated), **details}
            )
            handle.seek(0)
            handle.truncate()
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            return updated
