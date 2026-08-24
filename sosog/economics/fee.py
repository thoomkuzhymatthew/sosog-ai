"""Transparent cost-plus fee calculations over already-recorded cost events."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping

from .cost_model import money
from .inputs import decimal_string, decimal_value


@dataclass(frozen=True)
class FeeBreakdown:
    agent_cost_usd: Decimal
    infrastructure_cost_usd: Decimal
    recorded_cost_usd: Decimal
    markup_rate: Decimal
    markup_usd: Decimal
    fee_usd: Decimal

    def to_dict(self) -> dict[str, str]:
        return {name: decimal_string(money(value)) for name, value in (
            ("agent_cost_usd", self.agent_cost_usd),
            ("infrastructure_cost_usd", self.infrastructure_cost_usd),
            ("recorded_cost_usd", self.recorded_cost_usd),
            ("markup_usd", self.markup_usd), ("fee_usd", self.fee_usd))} | {
                "markup_rate": decimal_string(self.markup_rate)}


def calculate_fee(events: Iterable[Mapping[str, Any]], markup_rate: Any = "0.10") -> FeeBreakdown:
    rate = decimal_value(markup_rate, "markup_rate")
    agent = Decimal("0")
    infra = Decimal("0")
    for event in events:
        if not isinstance(event, Mapping):
            raise ValueError("cost event must be a mapping")
        kind = event.get("event_kind", event.get("cost_type", event.get("category")))
        if kind not in {
            "AGENT", "MODEL", "WORKER", "EVALUATOR", "INFRA", "INFRASTRUCTURE"
        }:
            raise ValueError(
                "event kind must identify agent/model or infrastructure cost"
            )
        amount = decimal_value(event.get("amount_usd"), "amount_usd")
        if kind in {"AGENT", "MODEL", "WORKER", "EVALUATOR"}:
            agent += amount
        else:
            infra += amount
    recorded = agent + infra
    markup = recorded * rate
    return FeeBreakdown(agent, infra, recorded, rate, markup, recorded + markup)
