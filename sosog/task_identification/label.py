"""Cluster-level Haiku labeling and task-type persistence."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Iterable

from .cluster import TaskCluster
from .embed import episode_summary


HAIKU_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Haiku response did not contain a JSON object")
    return json.loads(text[start : end + 1])


def label_cluster(cluster: TaskCluster, client: Any, *, model_id: str = HAIKU_MODEL_ID) -> TaskCluster:
    examples = "\n\n".join(
        f"Example {index}:\n{episode_summary(episode)}"
        for index, episode in enumerate(cluster.representative_episodes, 1)
    )
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 300,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": (
                "Identify the shared business task in these traces. Return only JSON "
                "with string fields 'name' (short) and 'description' (one paragraph).\n\n"
                + examples
            ),
        }],
    }
    response = client.invoke_model(
        modelId=model_id, contentType="application/json", accept="application/json", body=json.dumps(body)
    )
    payload = json.loads(response["body"].read())
    text = "".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text")
    label = _parse_json(text)
    name, description = label.get("name"), label.get("description")
    if not isinstance(name, str) or not name.strip() or not isinstance(description, str) or not description.strip():
        raise ValueError("Haiku label must contain non-empty name and description strings")
    return replace(cluster, name=name.strip(), description=description.strip())


def label_clusters(
    clusters: Iterable[TaskCluster], client: Any, *, store: Any | None = None, model_id: str = HAIKU_MODEL_ID
) -> list[TaskCluster]:
    """Call Haiku once per cluster and optionally write each task type."""
    labeled = [label_cluster(cluster, client, model_id=model_id) for cluster in clusters]
    if store is not None:
        for cluster in labeled:
            persisted = store.record_task_type({
                "task_type_id": cluster.task_type_id,
                "name": cluster.name,
                "description": cluster.description,
                "source": cluster.source,
                "representative_episode_ids": [episode.episode_id for episode in cluster.representative_episodes],
            })
            if not persisted:
                raise RuntimeError(f"failed to persist task type {cluster.task_type_id}")
    return labeled
