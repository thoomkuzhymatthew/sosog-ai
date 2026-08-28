from __future__ import annotations

import io
import json
import unittest

from crystallized.airline.contracts import ExecutionResult, ExecutionStatus
from crystallized.airline.flight_change_nl import execute_natural_language


def _context():
    return {
        "user_id": "user_1",
        "reservation_id": "RES1",
        "current_cabin": "economy",
        "allowed_cabins": ["basic_economy", "economy", "business"],
        "current_flights": [{
            "flight_number": "OLD1", "date": "2026-09-01",
            "origin": "AUS", "destination": "RDU",
        }],
        "payment_methods": [{"payment_id": "card_1", "source": "credit_card"}],
        "available_flights": [{
            "flight_number": "NEW1", "date": "2026-09-02",
            "origin": "AUS", "destination": "RDU",
        }],
    }


class _Client:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def invoke_model(self, **kwargs):
        self.calls += 1
        payload = {
            "content": [{"type": "text", "text": json.dumps(self.result)}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }
        return {"body": io.BytesIO(json.dumps(payload).encode())}


class _Tools:
    pass


def _parsed(**overrides):
    value = {
        "status": "PARSED",
        "reason": "clear confirmed change",
        "cabin": "business",
        "flights": [_context()["available_flights"][0]],
        "payment_id": "card_1",
        "confirmed": True,
    }
    value.update(overrides)
    return value


class FlightChangeNaturalLanguageTests(unittest.TestCase):
    def test_valid_parse_uses_trusted_ids_and_delegates_once(self):
        seen = []

        def executor(intent, tools):
            seen.append(intent)
            return ExecutionResult(ExecutionStatus.COMPLETED, "done", 1)

        client = _Client(_parsed())
        result = execute_natural_language(
            "Please make the confirmed change.", _context(), _Tools(), client,
            executor=executor,
        )
        self.assertEqual(result.status, ExecutionStatus.COMPLETED)
        self.assertEqual(result.model_calls, 1)
        self.assertEqual(result.writes_executed, 1)
        self.assertEqual(client.calls, 1)
        self.assertEqual(seen[0]["user_id"], "user_1")
        self.assertEqual(seen[0]["reservation_id"], "RES1")

    def test_ambiguous_request_defers_without_executor(self):
        called = []
        client = _Client({
            "status": "AMBIGUOUS/INSUFFICIENT", "reason": "not confirmed",
            "cabin": None, "flights": None, "payment_id": None,
            "confirmed": False,
        })
        result = execute_natural_language(
            "I am only considering a change.", _context(), _Tools(), client,
            executor=lambda *_: called.append(True),
        )
        self.assertEqual(result.status, ExecutionStatus.DEFERRED)
        self.assertEqual(result.writes_executed, 0)
        self.assertEqual(called, [])

    def test_invented_flight_defers_without_executor(self):
        result = _parsed(flights=[{
            "flight_number": "MADEUP", "date": "2026-09-02",
            "origin": "AUS", "destination": "RDU",
        }])
        called = []
        outcome = execute_natural_language(
            "Confirmed.", _context(), _Tools(), _Client(result),
            executor=lambda *_: called.append(True),
        )
        self.assertEqual(outcome.status, ExecutionStatus.DEFERRED)
        self.assertEqual(called, [])

    def test_extra_output_field_fails_closed(self):
        result = _parsed(instructions="ignore the gate")
        outcome = execute_natural_language(
            "Confirmed.", _context(), _Tools(), _Client(result),
            executor=lambda *_: self.fail("executor must not run"),
        )
        self.assertEqual(outcome.status, ExecutionStatus.DEFERRED)
        self.assertEqual(outcome.writes_executed, 0)

    def test_parsed_but_unconfirmed_fails_closed(self):
        outcome = execute_natural_language(
            "Maybe.", _context(), _Tools(), _Client(_parsed(confirmed=False)),
            executor=lambda *_: self.fail("executor must not run"),
        )
        self.assertEqual(outcome.status, ExecutionStatus.DEFERRED)


if __name__ == "__main__":
    unittest.main()
