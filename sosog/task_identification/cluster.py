"""Deterministic skeleton partitioning followed by HDBSCAN."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

import hdbscan
import numpy as np

from predictor.features import calls_for, skeleton
from sosog.ingestion.schema import NormalizedEpisode

from .embed import EpisodeEmbedding


@dataclass(frozen=True)
class TaskCluster:
    task_type_id: str
    member_episode_ids: tuple[str, ...]
    representative_episodes: tuple[NormalizedEpisode, ...]
    name: str = ""
    description: str = ""
    source: str = "AUTO_CLUSTERED"


def partition_key(episode: NormalizedEpisode, write_tools: set[str]) -> tuple:
    calls = calls_for({"calls": episode.calls}, write_tools)
    reads = Counter(call["name"] for call in calls if not call["is_write"])
    return skeleton(calls), tuple(sorted(reads.items()))


def partition_episodes(
    episodes: Iterable[NormalizedEpisode], write_tools: set[str]
) -> dict[tuple, list[NormalizedEpisode]]:
    buckets: dict[tuple, list[NormalizedEpisode]] = defaultdict(list)
    for episode in episodes:
        buckets[partition_key(episode, write_tools)].append(episode)
    return dict(buckets)


def cluster_episodes(
    episodes: Iterable[NormalizedEpisode],
    embeddings: Mapping[str, EpisodeEmbedding | Iterable[float]],
    *,
    write_tools: set[str],
    min_cluster_size: int = 2,
    representative_count: int = 3,
    min_samples: int | None = None,
) -> list[TaskCluster]:
    """Return only HDBSCAN clusters with sufficient evidence; discard noise."""
    if min_cluster_size < 2:
        raise ValueError("min_cluster_size must be at least 2")
    if representative_count < 1:
        raise ValueError("representative_count must be at least 1")
    accepted: list[TaskCluster] = []
    for _, bucket in sorted(partition_episodes(episodes, write_tools).items(), key=repr):
        if len(bucket) < min_cluster_size:
            continue
        vectors = []
        for episode in bucket:
            value = embeddings[episode.episode_id]
            vectors.append(value.vector if isinstance(value, EpisodeEmbedding) else tuple(value))
        if not vectors[0]:
            raise ValueError("embedding vectors must be non-empty")
        if len({len(vector) for vector in vectors}) != 1:
            raise ValueError("all embedding vectors in a bucket must have equal dimensions")
        if not all(isfinite(float(component)) for vector in vectors for component in vector):
            raise ValueError("embedding vectors must contain only finite numbers")
        labels = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            metric="euclidean",
        ).fit_predict(np.asarray(vectors, dtype=float))
        for label in sorted(set(int(value) for value in labels) - {-1}):
            members = sorted(
                (episode for episode, value in zip(bucket, labels) if int(value) == label),
                key=lambda episode: episode.episode_id,
            )
            if len(members) < min_cluster_size:
                continue
            member_ids = tuple(episode.episode_id for episode in members)
            stable_id = str(uuid5(NAMESPACE_URL, "sosog-task:" + "\0".join(member_ids)))
            accepted.append(
                TaskCluster(stable_id, member_ids, tuple(members[:representative_count]))
            )
    return sorted(accepted, key=lambda cluster: cluster.task_type_id)
