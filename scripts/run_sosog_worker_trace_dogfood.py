#!/usr/bin/env python3
"""Run completed SOSOG worker attempts through the V1 product pipeline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sosog.dogfood import run_worker_trace_dogfood  # noqa: E402
from sosog.persistence import SosogStore  # noqa: E402
from sosog.task_identification.embed import TITAN_EMBED_MODEL_ID  # noqa: E402
from sosog.task_identification.label import HAIKU_MODEL_ID  # noqa: E402
from sosog.task_identification.outcome_judge import (  # noqa: E402
    MODEL_ID as OUTCOME_MODEL_ID,
)


def discover(root: Path, prefixes: list[str], limit: int) -> list[Path]:
    paths = sorted(root.glob("*/traces/[0-9][0-9][0-9]/trace.jsonl"))
    if prefixes:
        paths = [
            path for path in paths
            if any(path.parents[2].name.startswith(prefix) for prefix in prefixes)
        ]
    return paths[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", nargs="*", type=Path)
    parser.add_argument(
        "--jobs-root", type=Path, default=Path("/opt/sosog/codex-agents/jobs")
    )
    parser.add_argument("--job-prefix", action="append", default=[])
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument(
        "--embedding-model",
        default=os.environ.get("BEDROCK_EMBED_MODEL_ID", TITAN_EMBED_MODEL_ID),
    )
    parser.add_argument(
        "--label-model",
        default=os.environ.get("BEDROCK_HAIKU_MODEL_ID", HAIKU_MODEL_ID),
    )
    parser.add_argument(
        "--outcome-model",
        default=os.environ.get("BEDROCK_HAIKU_MODEL_ID", OUTCOME_MODEL_ID),
    )
    parser.add_argument("--min-cluster-size", type=int, default=2)
    parser.add_argument("--min-samples", type=int, default=1)
    parser.add_argument("--min-complete-runs", type=int, default=5)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    paths = args.trace or discover(args.jobs_root, args.job_prefix, args.limit)
    if not paths:
        parser.error("no worker traces matched")

    import boto3

    result = run_worker_trace_dogfood(
        paths,
        store=SosogStore(),
        artifact_dir=args.artifact_dir,
        bedrock_client=boto3.client("bedrock-runtime", region_name=args.region),
        embedding_model_id=args.embedding_model,
        label_model_id=args.label_model,
        outcome_model_id=args.outcome_model,
        min_cluster_size=args.min_cluster_size,
        min_samples=args.min_samples,
        min_complete_runs=args.min_complete_runs,
    )
    print(json.dumps(result.summary(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
