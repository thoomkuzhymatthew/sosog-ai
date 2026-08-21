#!/usr/bin/env python3
"""Create deterministic difficulty-stratified AppWorld dev datasets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def stable_rank(task_id: str) -> str:
    return hashlib.sha256(f"sosog-m14:{task_id}".encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=60)
    args = parser.parse_args()

    os.environ["APPWORLD_ROOT"] = str(args.root)
    from appworld import load_task_ids, update_root

    update_root(str(args.root))
    buckets = {
        difficulty: sorted(load_task_ids("dev", difficulty=difficulty), key=stable_rank)
        for difficulty in (1, 2, 3)
    }
    selected: list[str] = []
    while len(selected) < args.count:
        progressed = False
        for difficulty in (1, 2, 3):
            if buckets[difficulty] and len(selected) < args.count:
                selected.append(buckets[difficulty].pop(0))
                progressed = True
        if not progressed:
            raise SystemExit(f"only found {len(selected)} dev tasks")

    dataset_dir = args.root / "data" / "datasets"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    (dataset_dir / "sosog_m14_60.txt").write_text("\n".join(selected) + "\n")
    smoke = [selected[index] for index in (0, 1, 2, 3, 4)]
    (dataset_dir / "sosog_m14_smoke.txt").write_text("\n".join(smoke) + "\n")
    payload = {
        "schema_version": 1,
        "source_dataset": "dev",
        "selection": "sha256 round-robin over difficulties 1, 2, 3",
        "task_ids": selected,
        "smoke_task_ids": smoke,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"rows": len(selected), "smoke_rows": len(smoke)}))


if __name__ == "__main__":
    main()
