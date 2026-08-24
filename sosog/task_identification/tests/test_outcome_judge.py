import io
import json
from datetime import datetime, timezone

from sosog.ingestion.schema import Cost, NormalizedEpisode, Outcome
from sosog.task_identification.outcome_judge import JudgedOutcome, judge_outcome


class FakeBedrockClient:
    def __init__(self, model_text: str):
        self.model_text = model_text
        self.calls = []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        payload = {"content": [{"type": "text", "text": self.model_text}]}
        return {"body": io.BytesIO(json.dumps(payload).encode())}


def make_episode(outcome: Outcome) -> NormalizedEpisode:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return NormalizedEpisode(
        episode_id="ep-1",
        task_type_id="returns",
        source_trace_id="trace-1",
        started_at=now,
        completed_at=now,
        calls=[
            {"tool": "lookup_order", "result": {"order_id": "order-1"}},
            {"tool": "issue_refund", "result": {"status": "completed"}},
        ],
        outcome=outcome,
        cost=Cost(),
        annotations={"final_response": "Your refund was issued."},
    )


def test_existing_evidence_passes_through_without_calling_judge():
    existing = Outcome(
        status="completed",
        success=True,
        success_source="programmatic_verifier",
        confidence=1.0,
    )
    client = FakeBedrockClient("should not be used")

    result = judge_outcome(make_episode(existing), "Issue the requested refund.", client)

    assert result is existing
    assert client.calls == []


def test_well_formed_response_produces_llm_judgment():
    client = FakeBedrockClient(
        json.dumps(
            {
                "success": True,
                "confidence": 0.93,
                "rationale": "The refund tool reports completion.",
            }
        )
    )

    result = judge_outcome(
        make_episode(Outcome(status="completed")),
        "Refund order: issue a refund for the requested order.",
        client,
    )

    assert result == JudgedOutcome(
        status="completed",
        success=True,
        success_source="llm_judged",
        confidence=0.93,
        rationale="The refund tool reports completion.",
    )
    assert len(client.calls) == 1
    request = client.calls[0]
    assert request["modelId"].endswith("haiku-4-5-20251001-v1:0")
    body = json.loads(request["body"])
    assert "Refund order" in body["messages"][0]["content"]
    assert "issue_refund" in body["messages"][0]["content"]


def test_model_override_is_used():
    client = FakeBedrockClient(
        '{"success": true, "confidence": 0.9, "rationale": "done"}'
    )

    judge_outcome(
        make_episode(Outcome(status="completed")),
        "Issue the refund.",
        client,
        model_id="test-model",
    )

    assert client.calls[0]["modelId"] == "test-model"


def test_empty_rubric_is_rejected_without_calling_judge():
    client = FakeBedrockClient("should not be used")

    try:
        judge_outcome(make_episode(Outcome(status="completed")), "  ", client)
    except ValueError as exc:
        assert "task_rubric" in str(exc)
    else:
        raise AssertionError("expected an empty rubric to be rejected")

    assert client.calls == []


def test_malformed_response_fails_safe_to_unknown():
    client = FakeBedrockClient(
        '{"success": "probably", "confidence": 0.8, "rationale": "looks good"}'
    )

    result = judge_outcome(
        make_episode(Outcome(status="completed")), "Issue the refund.", client
    )

    assert result.success is None
    assert result.success_source == "unknown"
    assert result.confidence is None
    assert "success must be a boolean" in result.rationale
    assert len(client.calls) == 1
