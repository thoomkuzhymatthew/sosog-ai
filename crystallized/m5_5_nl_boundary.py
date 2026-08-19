"""M5.5 NL boundary test for return tasks.

This is a narrow experiment harness, not a router or crystallization engine.
It calls a Haiku parser once per messy request, then reuses the M5
deterministic return executor for parsed return intents.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from m5_return_ladder import Lookup, ReturnRequest, run_self_resolved


MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
REGION = "us-east-1"

# Anthropic public pricing lists Claude Haiku 4.5 at $1/$5 per MTok.
# Regional Bedrock-style endpoints carry a 10% premium for Claude 4.5+.
HAIKU_INPUT_US_REGIONAL_PER_MTOK = 1.10
HAIKU_OUTPUT_US_REGIONAL_PER_MTOK = 5.50

SCRIPT_TOKENS = 0
SCRIPT_COST_USD = 0.0

CANONICAL_PRODUCT_NAMES = [
    "Action Camera",
    "Air Purifier",
    "Backpack",
    "Bicycle",
    "Bluetooth Speaker",
    "Bookshelf",
    "Coffee Maker",
    "Cycling Helmet",
    "Desk Lamp",
    "Digital Camera",
    "Dumbbell Set",
    "E-Reader",
    "Electric Kettle",
    "Electric Toothbrush",
    "Espresso Machine",
    "Fleece Jacket",
    "Gaming Mouse",
    "Garden Hose",
    "Grill",
    "Headphones",
    "Hiking Boots",
    "Indoor Security Camera",
    "Jigsaw Puzzle",
    "LED Light Bulb",
    "Laptop",
    "Luggage Set",
    "Makeup Kit",
    "Mechanical Keyboard",
    "Notebook",
    "Office Chair",
    "Patio Umbrella",
    "Perfume",
    "Pet Bed",
    "Portable Charger",
    "Running Shoes",
    "Skateboard",
    "Smart Thermostat",
    "Smart Watch",
    "Smartphone",
    "Sneakers",
    "Sunglasses",
    "T-Shirt",
    "Tablet",
    "Tea Kettle",
    "Vacuum Cleaner",
    "Wall Clock",
    "Water Bottle",
    "Wireless Earbuds",
    "Wristwatch",
    "Yoga Mat",
]

SYSTEM_PROMPT = f"""You extract a structured return intent from one retail support request.

Output only valid JSON in this exact shape:
{{
  "status": "PARSED" or "AMBIGUOUS/INSUFFICIENT",
  "reason": "short reason",
  "lookup": {{
    "method": "email" or "name_zip",
    "values": {{"email": "..."}}
      OR {{"first_name": "...", "last_name": "...", "zip": "..."}}
  }} or null,
  "return_item_names": ["Canonical Product Name"] or null,
  "keep_item_names": ["Canonical Product Name"] or null,
  "payment_rule": "original_payment_method" or null
}}

Rules:
- A PARSED intent must clearly ask to return or refund delivered retail item(s).
- A PARSED intent must include exactly one usable customer lookup: an email, or first name plus last name plus ZIP code.
- A PARSED intent must include either return_item_names or keep_item_names, not both.
- Use exact canonical product names from this catalog:
  {", ".join(CANONICAL_PRODUCT_NAMES)}
- If the customer's wording could map to multiple catalog products, mark AMBIGUOUS/INSUFFICIENT instead of guessing.
- If the customer mentions multiple unresolved actions, such as maybe exchanging and maybe returning, mark AMBIGUOUS/INSUFFICIENT.
- Treat "original payment", "same card", "back where it came from", or "whatever I paid with" as original_payment_method.
- Do not infer order IDs, user IDs, payment method IDs, or item IDs. The deterministic script resolves those later.
- If any required field is missing or uncertain, output AMBIGUOUS/INSUFFICIENT with null lookup, null item lists, and null payment_rule.
"""


@dataclass(frozen=True)
class ExpectedIntent:
    status: str
    lookup: dict[str, Any] | None
    return_item_names: list[str] | None = None
    keep_item_names: list[str] | None = None
    payment_rule: str | None = "original_payment_method"


@dataclass(frozen=True)
class TestCase:
    case_id: str
    task_id: str
    request_text: str
    expected: ExpectedIntent
    expected_category: str


TEST_CASES = [
    TestCase(
        case_id="5_a",
        task_id="5",
        request_text=(
            "Hi, Mei Kovacs here, zip 28236. After all the back and forth, "
            "forget the lamp swap. I just need the water bottle returned and "
            "the money put back where it came from."
        ),
        expected=ExpectedIntent(
            status="PARSED",
            lookup={
                "method": "name_zip",
                "values": {
                    "first_name": "Mei",
                    "last_name": "Kovacs",
                    "zip": "28236",
                },
            },
            return_item_names=["Water Bottle"],
        ),
        expected_category="unambiguous messy",
    ),
    TestCase(
        case_id="5_b",
        task_id="5",
        request_text=(
            "I'm Mei Kovacs in 28236. That bottle from my recent order is the "
            "one I ended up not wanting. Please process it as a return on the "
            "original payment."
        ),
        expected=ExpectedIntent(
            status="PARSED",
            lookup={
                "method": "name_zip",
                "values": {
                    "first_name": "Mei",
                    "last_name": "Kovacs",
                    "zip": "28236",
                },
            },
            return_item_names=["Water Bottle"],
        ),
        expected_category="missing last name",
    ),
    TestCase(
        case_id="5_c",
        task_id="5",
        request_text=(
            "I'm calling about that bottle and lamp order. I might exchange "
            "one thing or maybe return one, I honestly haven't decided."
        ),
        expected=ExpectedIntent(
            status="AMBIGUOUS/INSUFFICIENT",
            lookup=None,
            return_item_names=None,
            keep_item_names=None,
            payment_rule=None,
        ),
        expected_category="deliberately ambiguous",
    ),
    TestCase(
        case_id="13_a",
        task_id="13",
        request_text=(
            "This is Mia Garcia, mia.garcia2723@example.com. I went a little "
            "overboard on the gaming setup; keyboard and mouse are staying, "
            "everything else from that haul can go back. Original payment is "
            "fine."
        ),
        expected=ExpectedIntent(
            status="PARSED",
            lookup={
                "method": "email",
                "values": {"email": "mia.garcia2723@example.com"},
            },
            keep_item_names=["Mechanical Keyboard", "Gaming Mouse"],
        ),
        expected_category="keep-list indirect",
    ),
    TestCase(
        case_id="13_b",
        task_id="13",
        request_text=(
            "Mia here - email mia.garcia2723@example.com. Can you return the "
            "water bottle, action camera, and backpack? I'm keeping the actual "
            "keyboard/mouse stuff. Original payment is fine."
        ),
        expected=ExpectedIntent(
            status="PARSED",
            lookup={
                "method": "email",
                "values": {"email": "mia.garcia2723@example.com"},
            },
            return_item_names=["Water Bottle", "Action Camera", "Backpack"],
        ),
        expected_category="explicit return list",
    ),
    TestCase(
        case_id="13_c",
        task_id="13",
        request_text=(
            "I changed my mind on some gaming stuff. I only want the useful "
            "bits, I guess, but I don't have the order pulled up."
        ),
        expected=ExpectedIntent(
            status="AMBIGUOUS/INSUFFICIENT",
            lookup=None,
            return_item_names=None,
            keep_item_names=None,
            payment_rule=None,
        ),
        expected_category="deliberately ambiguous",
    ),
    TestCase(
        case_id="48_a",
        task_id="48",
        request_text=(
            "Daiki Johnson, Denver zip 80273. The air purifier showed up and "
            "it is useless, so please return that one to the original payment."
        ),
        expected=ExpectedIntent(
            status="PARSED",
            lookup={
                "method": "name_zip",
                "values": {
                    "first_name": "Daiki",
                    "last_name": "Johnson",
                    "zip": "80273",
                },
            },
            return_item_names=["Air Purifier"],
        ),
        expected_category="unambiguous messy",
    ),
    TestCase(
        case_id="48_b",
        task_id="48",
        request_text=(
            "Hey, I'm Daiki Johnson at 80273. In the order with the vacuum and "
            "umbrella, the purifier is the dud. Refund the purifier, not the "
            "vacuum."
        ),
        expected=ExpectedIntent(
            status="PARSED",
            lookup={
                "method": "name_zip",
                "values": {
                    "first_name": "Daiki",
                    "last_name": "Johnson",
                    "zip": "80273",
                },
            },
            return_item_names=["Air Purifier"],
        ),
        expected_category="extra distractors",
    ),
    TestCase(
        case_id="48_c",
        task_id="48",
        request_text=(
            "One of the appliances I bought doesn't work. It was the cleaner "
            "thing, or purifier thing maybe. Can you refund it?"
        ),
        expected=ExpectedIntent(
            status="AMBIGUOUS/INSUFFICIENT",
            lookup=None,
            return_item_names=None,
            keep_item_names=None,
            payment_rule=None,
        ),
        expected_category="deliberately ambiguous",
    ),
    TestCase(
        case_id="51_a",
        task_id="51",
        request_text=(
            "Sofia Li, San Antonio 78260. I need to return the digital camera; "
            "I guessed order W8855135 but honestly I'm not sure that's the one."
        ),
        expected=ExpectedIntent(
            status="PARSED",
            lookup={
                "method": "name_zip",
                "values": {
                    "first_name": "Sofia",
                    "last_name": "Li",
                    "zip": "78260",
                },
            },
            return_item_names=["Digital Camera"],
        ),
        expected_category="wrong order hint",
    ),
    TestCase(
        case_id="51_b",
        task_id="51",
        request_text=(
            "This is Sofia Li, 78260. The camera I received has to go back. "
            "Please refund it to the card I used."
        ),
        expected=ExpectedIntent(
            status="PARSED",
            lookup={
                "method": "name_zip",
                "values": {
                    "first_name": "Sofia",
                    "last_name": "Li",
                    "zip": "78260",
                },
            },
            return_item_names=["Digital Camera"],
        ),
        expected_category="synonym",
    ),
    TestCase(
        case_id="51_c",
        task_id="51",
        request_text=(
            "I think I gave the wrong order number earlier, but I want to "
            "return the electronics item from it."
        ),
        expected=ExpectedIntent(
            status="AMBIGUOUS/INSUFFICIENT",
            lookup=None,
            return_item_names=None,
            keep_item_names=None,
            payment_rule=None,
        ),
        expected_category="deliberately ambiguous",
    ),
    TestCase(
        case_id="53_a",
        task_id="53",
        request_text=(
            "Sofia Li, zip 78260. The bicycle arrived damaged in shipping and "
            "I want the refund back on my original card."
        ),
        expected=ExpectedIntent(
            status="PARSED",
            lookup={
                "method": "name_zip",
                "values": {
                    "first_name": "Sofia",
                    "last_name": "Li",
                    "zip": "78260",
                },
            },
            return_item_names=["Bicycle"],
        ),
        expected_category="unambiguous messy",
    ),
    TestCase(
        case_id="53_b",
        task_id="53",
        request_text=(
            "Sofia Li at 78260 here. The expensive bike got busted on the way "
            "over. I am pretty upset, so can you send that one back and credit "
            "the original payment?"
        ),
        expected=ExpectedIntent(
            status="PARSED",
            lookup={
                "method": "name_zip",
                "values": {
                    "first_name": "Sofia",
                    "last_name": "Li",
                    "zip": "78260",
                },
            },
            return_item_names=["Bicycle"],
        ),
        expected_category="synonym",
    ),
    TestCase(
        case_id="53_c",
        task_id="53",
        request_text=(
            "My expensive thing was damaged in shipping. I need a refund as "
            "soon as possible."
        ),
        expected=ExpectedIntent(
            status="AMBIGUOUS/INSUFFICIENT",
            lookup=None,
            return_item_names=None,
            keep_item_names=None,
            payment_rule=None,
        ),
        expected_category="deliberately ambiguous",
    ),
    TestCase(
        case_id="73_a",
        task_id="73",
        request_text=(
            "Fatima Wilson, fatima.wilson5721@example.com. I just bought a "
            "bunch of stuff but I'm only keeping the coffee machine; send "
            "everything else back."
        ),
        expected=ExpectedIntent(
            status="PARSED",
            lookup={
                "method": "email",
                "values": {"email": "fatima.wilson5721@example.com"},
            },
            keep_item_names=["Espresso Machine"],
        ),
        expected_category="catalog synonym collision",
    ),
    TestCase(
        case_id="73_b",
        task_id="73",
        request_text=(
            "Fatima here, email fatima.wilson5721@example.com. Keep the "
            "espresso machine. The boots, toothbrushes, and kettle should all "
            "be returned."
        ),
        expected=ExpectedIntent(
            status="PARSED",
            lookup={
                "method": "email",
                "values": {"email": "fatima.wilson5721@example.com"},
            },
            return_item_names=[
                "Hiking Boots",
                "Electric Toothbrush",
                "Electric Kettle",
            ],
        ),
        expected_category="plural item wording",
    ),
    TestCase(
        case_id="73_c",
        task_id="73",
        request_text=(
            "I want to return most of my latest order but keep the one thing "
            "for coffee."
        ),
        expected=ExpectedIntent(
            status="AMBIGUOUS/INSUFFICIENT",
            lookup=None,
            return_item_names=None,
            keep_item_names=None,
            payment_rule=None,
        ),
        expected_category="deliberately ambiguous",
    ),
]


def _normal_list(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return sorted(value.strip().lower() for value in values)


def _normal_intent(intent: dict[str, Any]) -> dict[str, Any]:
    lookup = intent.get("lookup")
    if lookup and isinstance(lookup, dict):
        values = lookup.get("values") or {}
        lookup = {
            "method": str(lookup.get("method", "")).strip().lower(),
            "values": {str(k): str(v).strip() for k, v in sorted(values.items())},
        }
    else:
        lookup = None
    return {
        "status": str(intent.get("status", "")).strip().upper(),
        "lookup": lookup,
        "return_item_names": _normal_list(intent.get("return_item_names")),
        "keep_item_names": _normal_list(intent.get("keep_item_names")),
        "payment_rule": (
            str(intent.get("payment_rule")).strip().lower()
            if intent.get("payment_rule") is not None
            else None
        ),
    }


def _expected_to_dict(expected: ExpectedIntent) -> dict[str, Any]:
    return {
        "status": expected.status,
        "lookup": expected.lookup,
        "return_item_names": expected.return_item_names,
        "keep_item_names": expected.keep_item_names,
        "payment_rule": expected.payment_rule,
    }


def _extract_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Haiku output was valid JSON but not an object")
    return parsed


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens * HAIKU_INPUT_US_REGIONAL_PER_MTOK
        + output_tokens * HAIKU_OUTPUT_US_REGIONAL_PER_MTOK
    ) / 1_000_000


def _invoke_haiku(client, request_text: str, *, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {
            "raw_text": json.dumps(
                {
                    "status": "AMBIGUOUS/INSUFFICIENT",
                    "reason": "dry run placeholder",
                    "lookup": None,
                    "return_item_names": None,
                    "keep_item_names": None,
                    "payment_rule": None,
                }
            ),
            "parsed_json": {
                "status": "AMBIGUOUS/INSUFFICIENT",
                "reason": "dry run placeholder",
                "lookup": None,
                "return_item_names": None,
                "keep_item_names": None,
                "payment_rule": None,
            },
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "cost_usd": 0.0,
        }

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "temperature": 0,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": f"Customer request:\n{request_text}",
            }
        ],
    }
    response = client.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    payload = json.loads(response["body"].read())
    raw_text = "".join(
        block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text"
    ).strip()
    parsed_json = _extract_json(raw_text)
    usage = payload.get("usage", {})
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return {
        "raw_text": raw_text,
        "parsed_json": parsed_json,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        "cost_usd": _estimate_cost(input_tokens, output_tokens),
    }


def _intent_correct(actual: dict[str, Any], expected: ExpectedIntent) -> bool:
    return _normal_intent(actual) == _normal_intent(_expected_to_dict(expected))


def _contract_warnings(parsed_json: dict[str, Any]) -> list[str]:
    warnings = []
    status = str(parsed_json.get("status", "")).strip().upper()
    return_items = parsed_json.get("return_item_names")
    keep_items = parsed_json.get("keep_item_names")
    if status != "PARSED":
        return warnings
    if return_items and keep_items:
        warnings.append("both return_item_names and keep_item_names populated")
    if not return_items and not keep_items:
        warnings.append("no return or keep item selector populated")
    if not parsed_json.get("lookup"):
        warnings.append("missing lookup")
    if parsed_json.get("payment_rule") is None:
        warnings.append("payment_rule null; deterministic script defaulted original method")
    return warnings


def _request_from_haiku(task_id: str, parsed_json: dict[str, Any]) -> ReturnRequest:
    lookup = parsed_json["lookup"]
    return ReturnRequest(
        task_id=task_id,
        lookup=Lookup(lookup["method"], lookup["values"]),
        return_item_names=parsed_json.get("return_item_names"),
        keep_item_names=parsed_json.get("keep_item_names"),
        payment_rule=parsed_json.get("payment_rule") or "original_payment_method",
        parameter_source="Haiku 4.5 parsed NL request",
    )


def _has_write(script_result: dict[str, Any] | None) -> bool:
    if not script_result:
        return False
    return any(
        call["name"] == "return_delivered_order_items"
        for call in script_result.get("executed_tool_calls", [])
    )


def _run_case(client, test_case: TestCase, *, dry_run: bool) -> dict[str, Any]:
    try:
        haiku = _invoke_haiku(client, test_case.request_text, dry_run=dry_run)
        parsed_json = haiku["parsed_json"]
        parser_error = None
    except (ClientError, json.JSONDecodeError, ValueError) as exc:
        return {
            "case_id": test_case.case_id,
            "task_id": test_case.task_id,
            "request_text": test_case.request_text,
            "expected_category": test_case.expected_category,
            "expected_intent": _expected_to_dict(test_case.expected),
            "haiku": None,
            "haiku_error": f"{type(exc).__name__}: {exc}",
            "intent_correct": False,
            "script_executed": False,
            "script_result": None,
            "script_error": None,
            "pipeline_pass": False,
            "outcome": "parse failure",
            "wrong_write": False,
        }

    strict_intent_match = _intent_correct(parsed_json, test_case.expected)
    contract_warnings = _contract_warnings(parsed_json)
    status = str(parsed_json.get("status", "")).strip().upper()
    script_result = None
    script_error = None
    script_executed = False

    if status == "PARSED":
        try:
            return_request = _request_from_haiku(test_case.task_id, parsed_json)
            script_result = run_self_resolved(test_case.case_id, return_request)
            script_executed = True
        except Exception as exc:  # noqa: BLE001 - stored as experimental result
            script_error = f"{type(exc).__name__}: {exc}"
            script_executed = True

    pipeline_pass = bool(script_result and script_result.get("pass") is True)
    expected_deferral = test_case.expected.status == "AMBIGUOUS/INSUFFICIENT"
    functional_intent_correct = bool(
        (expected_deferral and status == "AMBIGUOUS/INSUFFICIENT")
        or (not expected_deferral and status == "PARSED" and pipeline_pass)
    )
    if expected_deferral and status == "AMBIGUOUS/INSUFFICIENT":
        outcome = "correctly deferred"
    elif functional_intent_correct and pipeline_pass:
        outcome = "clean pass"
    elif strict_intent_match and not pipeline_pass:
        outcome = "downstream failure"
    else:
        outcome = "parse failure"

    wrong_write = bool(_has_write(script_result) and (expected_deferral or not pipeline_pass))

    return {
        "case_id": test_case.case_id,
        "task_id": test_case.task_id,
        "request_text": test_case.request_text,
        "expected_category": test_case.expected_category,
        "expected_intent": _expected_to_dict(test_case.expected),
        "haiku": haiku,
        "haiku_error": parser_error,
        "strict_intent_match": strict_intent_match,
        "functional_intent_correct": functional_intent_correct,
        "intent_correct": functional_intent_correct,
        "contract_warnings": contract_warnings,
        "script_executed": script_executed,
        "script_result": script_result,
        "script_error": script_error,
        "pipeline_pass": pipeline_pass,
        "outcome": outcome,
        "wrong_write": wrong_write,
    }


def _reclassify_result(result: dict[str, Any], test_case: TestCase) -> dict[str, Any]:
    haiku = result["haiku"]
    if haiku is None:
        result["strict_intent_match"] = False
        result["functional_intent_correct"] = False
        result["intent_correct"] = False
        result["contract_warnings"] = []
        result["outcome"] = "parse failure"
        result["wrong_write"] = False
        return result

    parsed_json = haiku["parsed_json"]
    status = str(parsed_json.get("status", "")).strip().upper()
    strict_intent_match = _intent_correct(parsed_json, test_case.expected)
    contract_warnings = _contract_warnings(parsed_json)
    pipeline_pass = bool(result.get("script_result") and result["script_result"].get("pass") is True)
    expected_deferral = test_case.expected.status == "AMBIGUOUS/INSUFFICIENT"
    functional_intent_correct = bool(
        (expected_deferral and status == "AMBIGUOUS/INSUFFICIENT")
        or (not expected_deferral and status == "PARSED" and pipeline_pass)
    )
    if expected_deferral and status == "AMBIGUOUS/INSUFFICIENT":
        outcome = "correctly deferred"
    elif functional_intent_correct and pipeline_pass:
        outcome = "clean pass"
    elif strict_intent_match and not pipeline_pass:
        outcome = "downstream failure"
    else:
        outcome = "parse failure"

    result["strict_intent_match"] = strict_intent_match
    result["functional_intent_correct"] = functional_intent_correct
    result["intent_correct"] = functional_intent_correct
    result["contract_warnings"] = contract_warnings
    result["outcome"] = outcome
    result["wrong_write"] = bool(
        _has_write(result.get("script_result")) and (expected_deferral or not pipeline_pass)
    )
    return result


def _load_m2_costs() -> dict[str, dict[str, Any]]:
    path = Path(__file__).resolve().parents[1] / "metrics" / "m2_per_task_costs.csv"
    rows = {}
    with path.open() as f:
        import csv

        for row in csv.DictReader(f):
            rows[row["task_id"]] = {
                "total_cost_cached_usd": float(row["total_cost_cached_usd"]),
                "counterfactual_total_cost_uncached_usd": float(
                    row["counterfactual_total_cost_uncached_usd"]
                ),
                "prompt_tokens": int(row["prompt_tokens"]),
                "completion_tokens": int(row["completion_tokens"]),
            }
    return rows


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    m2_costs = _load_m2_costs()
    outcome_counts: dict[str, int] = {}
    for result in results:
        outcome_counts[result["outcome"]] = outcome_counts.get(result["outcome"], 0) + 1

    task_ids = sorted({result["task_id"] for result in results}, key=int)
    sonnet_task_costs = {
        task_id: m2_costs[task_id]["total_cost_cached_usd"] for task_id in task_ids
    }
    haiku_total = sum(result["haiku"]["cost_usd"] for result in results if result["haiku"])
    input_tokens = sum(
        result["haiku"]["usage"]["input_tokens"] for result in results if result["haiku"]
    )
    output_tokens = sum(
        result["haiku"]["usage"]["output_tokens"] for result in results if result["haiku"]
    )
    clean_passes = outcome_counts.get("clean pass", 0)
    handled = clean_passes + outcome_counts.get("correctly deferred", 0)
    wrong_writes = sum(1 for result in results if result["wrong_write"])
    parse_failures = outcome_counts.get("parse failure", 0)
    deferrals = outcome_counts.get("correctly deferred", 0)
    return {
        "model_id": MODEL_ID,
        "region": REGION,
        "pricing": {
            "input_usd_per_mtok": HAIKU_INPUT_US_REGIONAL_PER_MTOK,
            "output_usd_per_mtok": HAIKU_OUTPUT_US_REGIONAL_PER_MTOK,
        },
        "tasks": task_ids,
        "request_count": len(results),
        "outcome_counts": outcome_counts,
        "clean_pass_rate": clean_passes / len(results),
        "handled_or_safely_deferred_rate": handled / len(results),
        "parse_failure_to_correct_deferral": {
            "parse_failures": parse_failures,
            "correct_deferrals": deferrals,
            "ratio": None if deferrals == 0 else parse_failures / deferrals,
        },
        "wrong_writes": wrong_writes,
        "haiku": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": haiku_total,
            "avg_cost_per_request_usd": haiku_total / len(results),
        },
        "script": {
            "tokens": SCRIPT_TOKENS,
            "cost_usd": SCRIPT_COST_USD,
        },
        "sonnet_agent_baseline_selected_tasks_cached_usd": sonnet_task_costs,
        "sonnet_agent_baseline_selected_tasks_total_cached_usd": sum(
            sonnet_task_costs.values()
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(
            Path(__file__).resolve().parents[1]
            / "metrics"
            / "m5_5_nl_boundary_results.json"
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--reclassify-existing",
        help="Recompute classifications from a saved result file without new model calls.",
    )
    args = parser.parse_args()

    if args.reclassify_existing:
        existing = json.loads(Path(args.reclassify_existing).read_text())
        cases = {case.case_id: case for case in TEST_CASES}
        results = [
            _reclassify_result(result, cases[result["case_id"]])
            for result in existing["results"]
        ]
    else:
        client = boto3.client("bedrock-runtime", region_name=REGION)
        results = []
        for test_case in TEST_CASES:
            result = _run_case(client, test_case, dry_run=args.dry_run)
            results.append(result)
            print(
                json.dumps(
                    {
                        "case_id": result["case_id"],
                        "task_id": result["task_id"],
                        "outcome": result["outcome"],
                        "pipeline_pass": result["pipeline_pass"],
                        "wrong_write": result["wrong_write"],
                        "haiku_tokens": (
                            result["haiku"]["usage"] if result["haiku"] else None
                        ),
                        "haiku_cost_usd": result["haiku"]["cost_usd"]
                        if result["haiku"]
                        else None,
                    },
                    sort_keys=True,
                )
            )

    output = {
        "summary": _summarize(results),
        "results": results,
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
