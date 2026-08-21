"""Deterministic, exact 70/30 held-out task-ID splits by vertical."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable


def split_task_ids(
    vertical: str, task_ids: Iterable[str], *, train_fraction: float = 0.70
) -> dict[str, list[str]]:
    unique = sorted({str(item) for item in task_ids})
    ranked = sorted(
        unique,
        key=lambda item: hashlib.sha256(f"sosog-m17:{vertical}:{item}".encode()).hexdigest(),
    )
    train_count = round(len(ranked) * train_fraction)
    return {
        "train": sorted(ranked[:train_count]),
        "held_out": sorted(ranked[train_count:]),
    }


def build_splits(records: list[dict]) -> dict[str, dict]:
    by_vertical: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_vertical[str(record["vertical"])].append(record)
    result = {}
    for vertical, items in sorted(by_vertical.items()):
        by_stratum: dict[str, list[str]] = defaultdict(list)
        for item in items:
            by_stratum[str(item.get("oracle_route", "all"))].append(str(item["task_id"]))
        strata = {
            name: split_task_ids(f"{vertical}:{name}", ids)
            for name, ids in sorted(by_stratum.items())
        }
        result[vertical] = {
            "train": sorted(task_id for split in strata.values() for task_id in split["train"]),
            "held_out": sorted(
                task_id for split in strata.values() for task_id in split["held_out"]
            ),
            "stratified_by": "oracle_route" if set(strata) != {"all"} else None,
            "strata": strata,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.corpus.read_text())
    records = data.get("tasks", data.get("features", data))
    payload = {
        "schema_version": 1,
        "method": "sha256 rank within vertical and oracle-route stratum; round(0.70 * stratum N) train",
        "verticals": build_splits(records),
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
