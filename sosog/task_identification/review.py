"""Non-blocking, post-hoc JSON corrections for task clusters."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from .cluster import TaskCluster


def load_overrides(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def _id(member_ids: Iterable[str]) -> str:
    return str(uuid5(NAMESPACE_URL, "sosog-task:" + "\0".join(sorted(member_ids))))


def apply_overrides(clusters: Iterable[TaskCluster], overrides: Mapping[str, Any]) -> list[TaskCluster]:
    """Apply optional merge, split, and rename operations without acting as a gate."""
    current = {cluster.task_type_id: cluster for cluster in clusters}
    for operation in overrides.get("merge", []):
        ids = operation["cluster_ids"]
        selected = [current.pop(cluster_id) for cluster_id in ids]
        members = sorted({item for cluster in selected for item in cluster.member_episode_ids})
        examples_by_id = {
            ep.episode_id: ep
            for cluster in selected
            for ep in cluster.representative_episodes
        }
        examples = tuple(examples_by_id[key] for key in sorted(examples_by_id))
        new_id = operation.get("task_type_id") or _id(members)
        current[new_id] = TaskCluster(
            new_id, tuple(members), examples[:3], operation.get("name", selected[0].name),
            operation.get("description", selected[0].description), "HUMAN_CONFIRMED",
        )
    for operation in overrides.get("split", []):
        original = current.pop(operation["cluster_id"])
        by_id = {ep.episode_id: ep for ep in original.representative_episodes}
        assigned: set[str] = set()
        for group in operation["groups"]:
            members = tuple(sorted(group["episode_ids"]))
            if not members or assigned.intersection(members):
                raise ValueError("split groups must be non-empty and disjoint")
            assigned.update(members)
            new_id = group.get("task_type_id") or _id(members)
            current[new_id] = TaskCluster(
                new_id, members, tuple(by_id[item] for item in members if item in by_id)[:3],
                group.get("name", original.name), group.get("description", original.description),
                "HUMAN_CONFIRMED",
            )
        if assigned != set(original.member_episode_ids):
            raise ValueError("split groups must cover every member episode exactly once")
    for cluster_id, values in overrides.get("rename", {}).items():
        cluster = current[cluster_id]
        current[cluster_id] = replace(
            cluster, name=values.get("name", cluster.name),
            description=values.get("description", cluster.description), source="HUMAN_CONFIRMED",
        )
    return sorted(current.values(), key=lambda cluster: cluster.task_type_id)


def persist_task_types(clusters: Iterable[TaskCluster], store: Any) -> list[bool]:
    return [store.record_task_type({
        "task_type_id": cluster.task_type_id, "name": cluster.name,
        "description": cluster.description, "source": cluster.source,
        "representative_episode_ids": [ep.episode_id for ep in cluster.representative_episodes],
    }) for cluster in clusters]
