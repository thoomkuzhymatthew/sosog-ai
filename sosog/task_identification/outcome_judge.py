"""Fill missing episode success labels with a single Bedrock judgment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sosog.ingestion.schema import NormalizedEpisode, Outcome


MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

SYSTEM_PROMPT = """You judge whether an agent episode accomplished its assigned business task.

Use the task rubric as the definition of success. Evaluate only evidence present in the episode detail; do not assume omitted actions or results succeeded. A tool call merely being attempted is not proof that its intended effect occurred. Account for errors, incomplete work, and outcome status.

Output only valid JSON in this exact shape:
{
  "success": true or false,
  "confidence": a number from 0.0 to 1.0,
  "rationale": "a concise evidence-based explanation"
}
"""

USER_PROMPT_TEMPLATE = """Task rubric:
{task_rubric}

Episode detail:
{episode_detail}

Judge whether this episode accomplished the task rubric."""


@dataclass(frozen=True)
class JudgedOutcome:
    """An outcome enriched with the LLM judge's explanation."""

    status: str
    success: bool | None
    success_source: str
    confidence: float | None
    rationale: str


def _episode_detail(episode: NormalizedEpisode) -> str:
    detail = {
        "episode_id": episode.episode_id,
        "calls": episode.calls,
        "outcome": {
            "status": episode.outcome.status,
            "success": episode.outcome.success,
            "success_source": episode.outcome.success_source,
            "confidence": episode.outcome.confidence,
        },
        "annotations": episode.annotations,
    }
    return json.dumps(detail, ensure_ascii=False, default=str, sort_keys=True)


def _failure(status: str, reason: str) -> JudgedOutcome:
    return JudgedOutcome(
        status=status,
        success=None,
        success_source="unknown",
        confidence=None,
        rationale=f"Could not parse LLM outcome judgment: {reason}",
    )


def _parse_judgment(raw_text: str, status: str) -> JudgedOutcome:
    try:
        result: Any = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError) as exc:
        return _failure(status, str(exc))

    if not isinstance(result, dict):
        return _failure(status, "response must be a JSON object")

    success = result.get("success")
    confidence = result.get("confidence")
    rationale = result.get("rationale")
    if not isinstance(success, bool):
        return _failure(status, "success must be a boolean")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return _failure(status, "confidence must be a number")
    if not 0.0 <= float(confidence) <= 1.0:
        return _failure(status, "confidence must be between 0.0 and 1.0")
    if not isinstance(rationale, str) or not rationale.strip():
        return _failure(status, "rationale must be a non-empty string")

    return JudgedOutcome(
        status=status,
        success=success,
        success_source="llm_judged",
        confidence=float(confidence),
        rationale=rationale.strip(),
    )


def judge_outcome(
    episode: NormalizedEpisode,
    task_rubric: str,
    client: Any,
    *,
    model_id: str = MODEL_ID,
) -> Outcome | JudgedOutcome:
    """Judge an unlabeled episode once, without overriding existing evidence."""
    if episode.outcome.success_source != "unknown":
        return episode.outcome
    if not isinstance(task_rubric, str) or not task_rubric.strip():
        raise ValueError("task_rubric must be a non-empty string")

    user_prompt = USER_PROMPT_TEMPLATE.format(
        task_rubric=task_rubric,
        episode_detail=_episode_detail(episode),
    )
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "temperature": 0,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    try:
        payload = json.loads(response["body"].read())
        raw_text = "".join(
            block.get("text", "")
            for block in payload.get("content", [])
            if block.get("type") == "text"
        ).strip()
    except (KeyError, AttributeError, TypeError, json.JSONDecodeError) as exc:
        return _failure(episode.outcome.status, f"invalid Bedrock response envelope: {exc}")
    return _parse_judgment(raw_text, episode.outcome.status)
