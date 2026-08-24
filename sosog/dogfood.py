"""Run SOSOG's own worker evidence through the V1 discovery/classifier path."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable
from uuid import NAMESPACE_URL, uuid5

from promotion_engine.classifier import build_promotion_plan
from promotion_engine.taxonomy import client_category_for
from sosog.ingestion.adapters.sosog_worker_trace import ingest_worker_trace
from sosog.ingestion.schema import NormalizedEpisode, Outcome
from sosog.task_identification.cluster import TaskCluster, cluster_episodes
from sosog.task_identification.embed import TITAN_EMBED_MODEL_ID, embed_episodes
from sosog.task_identification.label import HAIKU_MODEL_ID, label_cluster
from sosog.task_identification.outcome_judge import (
    MODEL_ID as OUTCOME_MODEL_ID,
    JudgedOutcome,
    judge_outcome,
)


CLASSIFIER_VERSION = "sosog-v1-worker-dogfood-1"


@dataclass(frozen=True)
class DogfoodResult:
    episodes: tuple[NormalizedEpisode, ...]
    clusters: tuple[TaskCluster, ...]
    promotion_plans: tuple[dict[str, Any], ...]
    classification_ids: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        return {
            "episode_count": len(self.episodes),
            "cluster_count": len(self.clusters),
            "unclustered_episode_count": sum(
                episode.task_type_id is None for episode in self.episodes
            ),
            "classification_count": len(self.classification_ids),
            "clusters": [
                {
                    "task_type_id": cluster.task_type_id,
                    "name": cluster.name,
                    "member_count": len(cluster.member_episode_ids),
                    "source": cluster.source,
                }
                for cluster in self.clusters
            ],
            "actions": [
                candidate["action"]
                for plan in self.promotion_plans
                for candidate in plan["candidates"]
            ],
        }


def _classifier_row(episode: NormalizedEpisode, task_type_id: str) -> dict[str, Any]:
    return {
        "task_id": task_type_id,
        "status": "COMPLETE",
        "passed": episode.outcome.success,
        "calls": episode.calls,
        "cost_usd": episode.cost.usd,
        "annotations": episode.annotations,
    }


def _classification_id(candidate: dict[str, Any], member_ids: tuple[str, ...]) -> str:
    evidence_hash = hashlib.sha256(
        json.dumps(
            {"candidate": candidate, "member_episode_ids": member_ids},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return str(uuid5(NAMESPACE_URL, f"{CLASSIFIER_VERSION}:{evidence_hash}"))


def run_worker_trace_dogfood(
    trace_paths: Iterable[str | Path],
    *,
    store: Any,
    artifact_dir: str | Path,
    bedrock_client: Any,
    embedding_model_id: str = TITAN_EMBED_MODEL_ID,
    label_model_id: str = HAIKU_MODEL_ID,
    outcome_model_id: str = OUTCOME_MODEL_ID,
    min_cluster_size: int = 2,
    min_samples: int | None = 1,
    min_complete_runs: int = 5,
) -> DogfoodResult:
    """Execute archive → normalize → discover → judge → classify → persist."""
    paths = sorted({Path(path) for path in trace_paths}, key=lambda path: str(path))
    if not paths:
        raise ValueError("at least one worker trace path is required")

    episodes = [
        ingest_worker_trace(path, store=store, artifact_dir=artifact_dir)
        for path in paths
    ]
    embeddings = embed_episodes(
        episodes, bedrock_client, model_id=embedding_model_id
    )
    clusters = cluster_episodes(
        episodes,
        {embedding.episode_id: embedding for embedding in embeddings},
        write_tools={"edit_files"},
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
    )
    labeled = []
    get_task_type = getattr(store, "get_task_type", None)
    for cluster in clusters:
        existing = get_task_type(cluster.task_type_id) if get_task_type else None
        if existing is not None:
            labeled.append(replace(
                cluster,
                name=existing["name"],
                description=existing["description"],
                source=existing["source"],
            ))
            continue
        resolved = label_cluster(cluster, bedrock_client, model_id=label_model_id)
        if not store.record_task_type({
            "task_type_id": resolved.task_type_id,
            "name": resolved.name,
            "description": resolved.description,
            "source": resolved.source,
            "representative_episode_ids": [
                episode.episode_id for episode in resolved.representative_episodes
            ],
        }):
            raise RuntimeError(f"failed to persist task type {resolved.task_type_id}")
        labeled.append(resolved)

    by_id = {episode.episode_id: episode for episode in episodes}
    for cluster in labeled:
        rubric = f"{cluster.name}\n\n{cluster.description}"
        for episode_id in cluster.member_episode_ids:
            episode = by_id[episode_id]
            if not store.assign_episode_task_type(episode_id, cluster.task_type_id):
                raise RuntimeError(f"failed to link worker episode {episode_id}")
            updated = replace(episode, task_type_id=cluster.task_type_id)
            if episode.outcome.success_source == "unknown":
                judged = judge_outcome(
                    episode,
                    rubric,
                    bedrock_client,
                    model_id=outcome_model_id,
                )
                if isinstance(judged, JudgedOutcome):
                    if not store.update_episode_outcome(
                        episode_id,
                        success=judged.success,
                        success_source=judged.success_source,
                        confidence=judged.confidence,
                        rationale=judged.rationale,
                    ):
                        raise RuntimeError(f"failed to persist outcome for {episode_id}")
                    updated = replace(
                        updated,
                        outcome=Outcome(
                            status=judged.status,
                            success=judged.success,
                            success_source=judged.success_source,
                            confidence=judged.confidence,
                        ),
                        annotations={
                            **updated.annotations,
                            "outcome_judge_rationale": judged.rationale,
                        },
                    )
            by_id[episode_id] = updated

    plans = []
    classification_ids = []
    for cluster in labeled:
        known = [
            by_id[episode_id]
            for episode_id in cluster.member_episode_ids
            if by_id[episode_id].outcome.success is not None
        ]
        plan = build_promotion_plan(
            "sosog_internal",
            [_classifier_row(episode, cluster.task_type_id) for episode in known],
            write_tools={"edit_files"},
            min_complete_runs=min_complete_runs,
        )
        plans.append(plan)
        for candidate in plan["candidates"]:
            classification_id = _classification_id(
                candidate, cluster.member_episode_ids
            )
            evidence = candidate["evidence"]
            get_classification = getattr(store, "get_classification", None)
            existing_classification = (
                get_classification(classification_id) if get_classification else None
            )
            if existing_classification is None and not store.record_classification({
                "classification_id": classification_id,
                "task_type_id": cluster.task_type_id,
                "classifier_version": CLASSIFIER_VERSION,
                "features": {
                    "vertical": "sosog_internal",
                    "member_episode_ids": list(cluster.member_episode_ids),
                    "known_outcome_count": len(known),
                },
                "internal_action": candidate["action"],
                "product_category": client_category_for(candidate["action"]),
                "evidence": evidence,
                "confidence": evidence["confidence"],
            }):
                raise RuntimeError(
                    f"failed to persist classification {classification_id}"
                )
            classification_ids.append(classification_id)

    return DogfoodResult(
        episodes=tuple(by_id[episode.episode_id] for episode in episodes),
        clusters=tuple(labeled),
        promotion_plans=tuple(plans),
        classification_ids=tuple(classification_ids),
    )
