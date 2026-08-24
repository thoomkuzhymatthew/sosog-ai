"""Bedrock Titan embeddings for normalized episodes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from sosog.ingestion.schema import NormalizedEpisode


TITAN_EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"


@dataclass(frozen=True)
class EpisodeEmbedding:
    episode_id: str
    text: str
    vector: tuple[float, ...]


def episode_summary(episode: NormalizedEpisode, *, max_calls: int = 12) -> str:
    """Build a bounded, stable description from the request and call trace."""
    request = next(
        (
            episode.annotations[key]
            for key in ("initial_request", "request", "user_request", "prompt")
            if isinstance(episode.annotations.get(key), str)
            and episode.annotations[key].strip()
        ),
        "",
    )
    rendered = []
    for call in episode.calls[:max_calls]:
        name = str(call.get("name") or call.get("tool_name") or "unknown")
        arguments = call.get("arguments", call.get("args", {}))
        rendered.append(f"{name}({json.dumps(arguments, sort_keys=True, default=str)})")
    parts = []
    if request:
        parts.append(f"Initial request: {request.strip()}")
    parts.append("Trace: " + (" -> ".join(rendered) or "no tool calls"))
    if len(episode.calls) > max_calls:
        parts.append(f"({len(episode.calls) - max_calls} additional calls omitted)")
    return "\n".join(parts)


def embed_episode(
    episode: NormalizedEpisode,
    client: Any,
    *,
    model_id: str = TITAN_EMBED_MODEL_ID,
) -> EpisodeEmbedding:
    """Make exactly one Titan V2 embedding request for an episode."""
    input_text = episode_summary(episode)
    body = {"inputText": input_text, "dimensions": 1024, "normalize": True}
    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    payload = json.loads(response["body"].read())
    vector = payload.get("embedding")
    if not isinstance(vector, list) or not vector:
        raise ValueError("Titan embedding response is missing a non-empty 'embedding' list")
    return EpisodeEmbedding(episode.episode_id, input_text, tuple(float(x) for x in vector))


def embed_episodes(
    episodes: Iterable[NormalizedEpisode], client: Any, *, model_id: str = TITAN_EMBED_MODEL_ID
) -> list[EpisodeEmbedding]:
    return [embed_episode(episode, client, model_id=model_id) for episode in episodes]
