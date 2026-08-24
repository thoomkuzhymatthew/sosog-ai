"""Immutable versioned inputs for economics projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"


def _validate_mapping_keys(
    value: Mapping[str, Any], *, allowed: frozenset[str], required: frozenset[str], name: str
) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise ValueError(f"{name} has unknown fields: {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"{name} is missing fields: {', '.join(sorted(missing))}")


class EvidenceQuality(StrEnum):
    MEASURED = "MEASURED"
    ESTIMATED = "ESTIMATED"


class Period(StrEnum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    QUARTER = "QUARTER"
    YEAR = "YEAR"


def decimal_value(value: Any, name: str, *, minimum: Decimal = Decimal("0")) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a finite decimal") from exc
    if not result.is_finite() or result < minimum:
        raise ValueError(f"{name} must be a finite decimal >= {minimum}")
    return result


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def decimal_string(value: Decimal) -> str:
    """Canonical non-exponent JSON representation without losing precision."""
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


@dataclass(frozen=True)
class VolumeInput:
    task_type_id: str
    frequency: str
    unit_count: Decimal
    period: Period
    source: str
    as_of_date: date
    quality: EvidenceQuality
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_type_id", _text(self.task_type_id, "task_type_id"))
        object.__setattr__(self, "frequency", _text(self.frequency, "frequency"))
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(self, "unit_count", decimal_value(self.unit_count, "unit_count"))
        object.__setattr__(self, "period", Period(self.period))
        object.__setattr__(self, "quality", EvidenceQuality(self.quality))
        if type(self.as_of_date) is not date:
            raise ValueError("as_of_date must be a date, not a datetime")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported volume schema_version: {self.schema_version}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "VolumeInput":
        if not isinstance(value, Mapping):
            raise ValueError("volume must be a mapping")
        fields = frozenset({
            "schema_version", "task_type_id", "frequency", "unit_count", "period",
            "source", "as_of_date", "quality",
        })
        _validate_mapping_keys(
            value, allowed=fields, required=fields - {"schema_version"}, name="volume"
        )
        try:
            as_of = date.fromisoformat(value["as_of_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("as_of_date must be an ISO date") from exc
        return cls(
            task_type_id=value.get("task_type_id"), frequency=value.get("frequency"),
            unit_count=value.get("unit_count"), period=value.get("period"),
            source=value.get("source"), as_of_date=as_of, quality=value.get("quality"),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "task_type_id": self.task_type_id,
            "frequency": self.frequency, "unit_count": decimal_string(self.unit_count),
            "period": self.period.value, "source": self.source,
            "as_of_date": self.as_of_date.isoformat(), "quality": self.quality.value,
        }


@dataclass(frozen=True)
class CostAssumptions:
    task_type_id: str
    current_agent_cost_usd: Decimal
    fixed_automation_cost_usd: Decimal
    prefix_cost_usd: Decimal
    tail_fraction: Decimal
    source: str
    as_of_date: date
    quality: EvidenceQuality
    confidence: Decimal
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_type_id", _text(self.task_type_id, "task_type_id"))
        object.__setattr__(self, "source", _text(self.source, "source"))
        for name in ("current_agent_cost_usd", "fixed_automation_cost_usd", "prefix_cost_usd"):
            object.__setattr__(self, name, decimal_value(getattr(self, name), name))
        for name in ("tail_fraction", "confidence"):
            parsed = decimal_value(getattr(self, name), name)
            if parsed > 1:
                raise ValueError(f"{name} must be between zero and one")
            object.__setattr__(self, name, parsed)
        object.__setattr__(self, "quality", EvidenceQuality(self.quality))
        if type(self.as_of_date) is not date:
            raise ValueError("as_of_date must be a date, not a datetime")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported cost schema_version: {self.schema_version}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CostAssumptions":
        if not isinstance(value, Mapping):
            raise ValueError("cost assumptions must be a mapping")
        fields = frozenset({
            "schema_version", "task_type_id", "current_agent_cost_usd",
            "fixed_automation_cost_usd", "prefix_cost_usd", "tail_fraction", "source",
            "as_of_date", "quality", "confidence",
        })
        _validate_mapping_keys(
            value, allowed=fields, required=fields - {"schema_version"},
            name="cost assumptions",
        )
        try:
            as_of = date.fromisoformat(value["as_of_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("as_of_date must be an ISO date") from exc
        return cls(**{key: value.get(key) for key in (
            "task_type_id", "current_agent_cost_usd", "fixed_automation_cost_usd",
            "prefix_cost_usd", "tail_fraction", "source", "quality", "confidence")},
            as_of_date=as_of, schema_version=value.get("schema_version", SCHEMA_VERSION))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "task_type_id": self.task_type_id,
            "current_agent_cost_usd": decimal_string(self.current_agent_cost_usd),
            "fixed_automation_cost_usd": decimal_string(self.fixed_automation_cost_usd),
            "prefix_cost_usd": decimal_string(self.prefix_cost_usd),
            "tail_fraction": decimal_string(self.tail_fraction), "source": self.source,
            "as_of_date": self.as_of_date.isoformat(), "quality": self.quality.value,
            "confidence": decimal_string(self.confidence),
        }
