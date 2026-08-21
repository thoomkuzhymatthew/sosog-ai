#!/usr/bin/env python3
"""Select 40 deterministic WebArena tasks that need only installed local sites."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


ALLOWED_SITES = {"shopping", "shopping_admin", "reddit", "gitlab", "wikipedia"}


def rank(value: str) -> str:
    return hashlib.sha256(f"sosog-m16:{value}".encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configs", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=40)
    args = parser.parse_args()
    rows = json.loads(args.configs.read_text())
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        sites = set(row["sites"])
        if sites and sites <= ALLOWED_SITES:
            buckets[sorted(sites)[0]].append(row)
    for bucket in buckets.values():
        bucket.sort(key=lambda row: rank(str(row["task_id"])))
    selected = []
    while len(selected) < args.count:
        progressed = False
        for site in sorted(buckets, key=rank):
            if buckets[site] and len(selected) < args.count:
                selected.append(buckets[site].pop(0))
                progressed = True
        if not progressed:
            raise SystemExit(f"only found {len(selected)} compatible tasks")
    task_ids = [int(row["task_id"]) for row in selected]
    payload = {
        "schema_version": 1,
        "source": "WebArena v0.2.0 canonical 812-task set",
        "selection": "SHA-256 round-robin by primary site; map tasks excluded",
        "installed_sites": sorted(ALLOWED_SITES),
        "task_ids": task_ids,
        "smoke_task_ids": task_ids[:5],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"rows": len(task_ids), "smoke_rows": 5}))


if __name__ == "__main__":
    main()
