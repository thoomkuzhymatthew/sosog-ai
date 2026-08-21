#!/usr/bin/env python3
"""Select a deterministic, repository-and-size-stratified SWE Verified slice."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def rank(value: str) -> str:
    return hashlib.sha256(f"sosog-m15:{value}".encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=60)
    args = parser.parse_args()

    from datasets import load_dataset

    rows = list(load_dataset("princeton-nlp/SWE-Bench_Verified", split="test"))
    lengths = sorted(len(row["problem_statement"]) for row in rows)
    low, high = lengths[len(lengths) // 3], lengths[(2 * len(lengths)) // 3]

    def size_bucket(row: dict) -> str:
        length = len(row["problem_statement"])
        return "short" if length <= low else "medium" if length <= high else "long"

    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        buckets[(row["repo"], size_bucket(row))].append(row)
    for bucket in buckets.values():
        bucket.sort(key=lambda row: rank(row["instance_id"]))
    bucket_keys = sorted(buckets, key=lambda key: rank(":".join(key)))

    selected: list[dict] = []
    while len(selected) < args.count:
        progressed = False
        for key in bucket_keys:
            if buckets[key] and len(selected) < args.count:
                selected.append(buckets[key].pop(0))
                progressed = True
        if not progressed:
            raise SystemExit(f"only found {len(selected)} tasks")

    # Preserve the upstream dataset order because mini-SWE-agent applies
    # --slice before any other durable identifier is emitted.
    all_ids = [row["instance_id"] for row in rows]
    selected_ids = [row["instance_id"] for row in selected]
    payload = {
        "schema_version": 1,
        "source_dataset": "princeton-nlp/SWE-Bench_Verified:test",
        "selection": "round-robin over repository and problem-length tercile, SHA-256 ranked",
        "baseline_task_ids": all_ids,
        "task_ids": selected_ids,
        "golden_task_ids": selected_ids[:3],
        "haiku_task_ids": selected_ids[:5],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"baseline_rows": len(all_ids), "corpus_rows": len(selected_ids)}))


if __name__ == "__main__":
    main()
