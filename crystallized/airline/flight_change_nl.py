"""Cheap natural-language boundary for the deterministic Airline flight-change executor.

The model may select only values present in a controller-supplied context. Its
output is untrusted: this module applies a strict schema/allowlist gate before
passing a canonical intent to the deterministic executor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .contracts import ExecutionResult, ExecutionStatus, ToolClient


MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
INPUT_USD_PER_MTOK = 1.10
OUTPUT_USD_PER_MTOK = 5.50

_CABINS = {"basic_economy", "economy", "business"}
_RESULT_KEYS = {"status", "reason", "cabin", "flights", "payment_id", "confirmed"}
_FLIGHT_KEYS = {"flight_number", "date", "origin", "destination"}

SYSTEM_PROMPT = """You extract one requested airline flight change.

Return only one JSON object with exactly these fields:
{
  "status": "PARSED" or "AMBIGUOUS/INSUFFICIENT",
  "reason": "short reason",
  "cabin": "basic_economy", "economy", or "business", or null,
  "flights": [
    {"flight_number":"...","date":"YYYY-MM-DD","origin":"AAA","destination":"BBB"}
  ] or null,
  "payment_id": "one allowed payment_id" or null,
  "confirmed": true or false
}

Rules:
- Select only exact values and complete flight objects from ALLOWED CONTEXT.
- Select cabin only from allowed_cabins. Cabin is an independent requested
  field: current_cabin and flight objects do not indicate cabin availability.
  Do not infer cabin availability or policy; those are checked downstream.
- The flights list is the complete replacement itinerary, in travel order.
- PARSED requires an unambiguous cabin, complete itinerary, payment method,
  and explicit confirmation to execute the complete change now.
- Do not treat a tentative request, information request, price question, or
  request lacking final confirmation as confirmed.
- Do not invent, normalize, or repair identifiers, dates, airports, flights,
  cabins, or payment IDs.
- If anything is missing, conflicting, or uncertain, return
  AMBIGUOUS/INSUFFICIENT with cabin/flights/payment_id null and confirmed false.
"""


@dataclass(frozen=True)
class ParseOutcome:
    status: str
    reason: str
    intent: dict[str, Any] | None
    input_tokens: int = 0
    output_tokens: int = 0


def _json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response did not contain a JSON object")
    parsed = json.loads(value[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("response must be a JSON object")
    return parsed


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _validated_context(context: Any) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        raise ValueError("allowed context must be an object")
    required = {
        "user_id", "reservation_id", "current_cabin", "allowed_cabins",
        "current_flights", "payment_methods", "available_flights",
    }
    if set(context) != required:
        raise ValueError("allowed context keys do not match schema")
    if not _nonempty(context["user_id"]) or not _nonempty(context["reservation_id"]):
        raise ValueError("trusted user and reservation IDs are required")
    if context["current_cabin"] not in _CABINS:
        raise ValueError("current cabin is invalid")
    allowed_cabins = context["allowed_cabins"]
    if (
        not isinstance(allowed_cabins, list)
        or not allowed_cabins
        or len(set(allowed_cabins)) != len(allowed_cabins)
        or any(cabin not in _CABINS for cabin in allowed_cabins)
    ):
        raise ValueError("allowed_cabins must contain unique supported cabins")
    for collection in ("current_flights", "available_flights"):
        rows = context[collection]
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{collection} must be non-empty")
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != _FLIGHT_KEYS:
                raise ValueError(f"{collection} contains an invalid flight")
            if not all(_nonempty(row[key]) for key in _FLIGHT_KEYS):
                raise ValueError(f"{collection} contains a blank flight field")
    methods = context["payment_methods"]
    if not isinstance(methods, list) or not methods:
        raise ValueError("payment_methods must be non-empty")
    for method in methods:
        if (
            not isinstance(method, Mapping)
            or set(method) != {"payment_id", "source"}
            or not _nonempty(method["payment_id"])
            or not _nonempty(method["source"])
        ):
            raise ValueError("payment_methods contains an invalid entry")
    trusted = dict(context)
    trusted["allowed_cabins"] = list(allowed_cabins)
    trusted["current_flights"] = [dict(row) for row in context["current_flights"]]
    trusted["payment_methods"] = [dict(row) for row in context["payment_methods"]]
    trusted["available_flights"] = [dict(row) for row in context["available_flights"]]
    return trusted


def _validate_model_result(result: Any, context: dict[str, Any]) -> ParseOutcome:
    if not isinstance(result, Mapping) or set(result) != _RESULT_KEYS:
        raise ValueError("parser output keys do not match schema")
    status, reason = result["status"], result["reason"]
    if status not in {"PARSED", "AMBIGUOUS/INSUFFICIENT"} or not _nonempty(reason):
        raise ValueError("parser status or reason is invalid")
    if status == "AMBIGUOUS/INSUFFICIENT":
        if any(result[key] is not None for key in ("cabin", "flights", "payment_id")):
            raise ValueError("ambiguous output must not contain an executable selection")
        if result["confirmed"] is not False:
            raise ValueError("ambiguous output cannot be confirmed")
        return ParseOutcome(status, reason, None)

    if result["cabin"] not in context["allowed_cabins"] or result["confirmed"] is not True:
        raise ValueError("parsed output lacks a supported cabin or confirmation")
    flights = result["flights"]
    if not isinstance(flights, list) or not flights:
        raise ValueError("parsed output lacks a complete itinerary")
    allowed_flights = context["available_flights"]
    canonical_flights: list[dict[str, str]] = []
    for flight in flights:
        if not isinstance(flight, Mapping) or set(flight) != _FLIGHT_KEYS:
            raise ValueError("parsed output contains an invalid flight")
        candidate = dict(flight)
        if candidate not in allowed_flights:
            raise ValueError("parsed output selected a flight outside allowed context")
        canonical_flights.append(candidate)
    payment_ids = {method["payment_id"] for method in context["payment_methods"]}
    if result["payment_id"] not in payment_ids:
        raise ValueError("parsed output selected a payment outside allowed context")
    intent = {
        "user_id": context["user_id"],
        "reservation_id": context["reservation_id"],
        "cabin": result["cabin"],
        "flights": canonical_flights,
        "payment_id": result["payment_id"],
        "confirmed": True,
    }
    return ParseOutcome(status, reason, intent)


def parse_request(
    request_text: str,
    allowed_context: Any,
    bedrock_client: Any,
    *,
    model_id: str = MODEL_ID,
) -> ParseOutcome:
    """Make one Haiku call and validate its selection against trusted context."""
    if not _nonempty(request_text):
        raise ValueError("request text must be non-empty")
    context = _validated_context(allowed_context)
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 700,
        "temperature": 0,
        "system": SYSTEM_PROMPT,
        "messages": [{
            "role": "user",
            "content": (
                "ALLOWED CONTEXT:\n"
                + json.dumps(context, sort_keys=True, separators=(",", ":"))
                + "\n\nCUSTOMER REQUEST:\n"
                + request_text
            ),
        }],
    }
    response = bedrock_client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    payload = json.loads(response["body"].read())
    text = "".join(
        block.get("text", "")
        for block in payload.get("content", [])
        if block.get("type") == "text"
    )
    outcome = _validate_model_result(_json_object(text), context)
    usage = payload.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    if isinstance(input_tokens, bool) or not isinstance(input_tokens, int) or input_tokens < 0:
        input_tokens = 0
    if isinstance(output_tokens, bool) or not isinstance(output_tokens, int) or output_tokens < 0:
        output_tokens = 0
    return ParseOutcome(
        outcome.status,
        outcome.reason,
        outcome.intent,
        input_tokens,
        output_tokens,
    )


def execute_natural_language(
    request_text: str,
    allowed_context: Any,
    tools: ToolClient,
    bedrock_client: Any,
    *,
    model_id: str = MODEL_ID,
    executor: Callable[[Any, ToolClient], ExecutionResult] | None = None,
) -> ExecutionResult:
    """Parse once, fail closed, then delegate the only possible write."""
    try:
        parsed = parse_request(request_text, allowed_context, bedrock_client, model_id=model_id)
    except Exception as exc:
        return ExecutionResult(
            ExecutionStatus.DEFERRED,
            f"language boundary could not prove intent: {type(exc).__name__}",
            0,
            model_calls=1,
            details={"stage": "language_gate", "input_tokens": 0, "output_tokens": 0},
        )
    usage = {"input_tokens": parsed.input_tokens, "output_tokens": parsed.output_tokens}
    if parsed.intent is None:
        return ExecutionResult(
            ExecutionStatus.DEFERRED,
            parsed.reason,
            0,
            model_calls=1,
            details={"stage": "language_gate", **usage},
        )
    if executor is None:
        from .flight_change import execute_flight_change

        executor = execute_flight_change
    result = executor(parsed.intent, tools)
    return ExecutionResult(
        result.status,
        result.reason,
        result.writes_executed,
        model_calls=result.model_calls + 1,
        details={**result.details, "language_boundary": "haiku_allowlisted_v1", **usage},
    )


def measured_cost_usd(result: ExecutionResult) -> float:
    """Compute parser cost from Bedrock-reported tokens."""
    input_tokens = result.details.get("input_tokens", 0)
    output_tokens = result.details.get("output_tokens", 0)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return 0.0
    return (
        input_tokens * INPUT_USD_PER_MTOK
        + output_tokens * OUTPUT_USD_PER_MTOK
    ) / 1_000_000
