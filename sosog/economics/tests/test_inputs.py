from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
import unittest

from sosog.economics.inputs import (
    CostAssumptions,
    EvidenceQuality,
    Period,
    VolumeInput,
)


def volume(quality=EvidenceQuality.MEASURED, period=Period.MONTH, task="task"):
    return VolumeInput(
        task, "100 occurrences", "100", period, "client ledger",
        date(2026, 8, 1), quality,
    )


def costs(quality=EvidenceQuality.MEASURED, task="task"):
    return CostAssumptions(
        task, "2", ".10", ".20", ".25", "agent cost ledger",
        date(2026, 8, 1), quality, ".90",
    )


class EconomicsInputTests(unittest.TestCase):
    def test_mapping_round_trip_and_serialization_are_deterministic(self):
        original = volume()
        self.assertEqual(VolumeInput.from_mapping(original.to_dict()), original)
        original_costs = costs()
        self.assertEqual(
            CostAssumptions.from_mapping(original_costs.to_dict()), original_costs
        )
        serialized = json.dumps(original.to_dict(), sort_keys=True)
        self.assertEqual(serialized, json.dumps(original.to_dict(), sort_keys=True))
        self.assertIsInstance(original.to_dict()["unit_count"], str)

    def test_every_supported_period_round_trips(self):
        for period in Period:
            with self.subTest(period=period):
                restored = VolumeInput.from_mapping(volume(period=period).to_dict())
                self.assertIs(restored.period, period)

    def test_mapping_inputs_reject_missing_and_unknown_fields(self):
        missing = volume().to_dict()
        del missing["source"]
        with self.assertRaisesRegex(ValueError, "missing fields"):
            VolumeInput.from_mapping(missing)
        unknown = volume().to_dict() | {"benchmark_episode_count": 1000}
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            VolumeInput.from_mapping(unknown)

    def test_malformed_values_are_rejected(self):
        constructors = (
            lambda: VolumeInput(
                "", "daily", 1, Period.DAY, "client", date.today(),
                EvidenceQuality.MEASURED,
            ),
            lambda: VolumeInput(
                "x", "daily", -1, Period.DAY, "client", date.today(),
                EvidenceQuality.MEASURED,
            ),
            lambda: CostAssumptions(
                "x", 1, 0, 0, "1.01", "src", date.today(),
                EvidenceQuality.MEASURED, 1,
            ),
        )
        for constructor in constructors:
            with self.subTest(constructor=constructor):
                with self.assertRaises(ValueError):
                    constructor()

    def test_dates_do_not_silently_accept_timestamps(self):
        with self.assertRaisesRegex(ValueError, "datetime"):
            VolumeInput(
                "x", "daily", Decimal("1"), Period.DAY, "client",
                datetime.now(), EvidenceQuality.MEASURED,
            )


if __name__ == "__main__":
    unittest.main()
