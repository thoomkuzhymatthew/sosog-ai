#!/usr/bin/env python3
"""Build an AppWorld resume dataset without splitting scenario groups."""

from __future__ import annotations

import argparse
from collections import OrderedDict
from pathlib import Path


def scenario_id(task_id: str) -> str:
    """Return the scenario prefix from an AppWorld task ID."""
    scenario, separator, task_number = task_id.rpartition("_")
    if not separator or not scenario or not task_number.isdigit():
        raise ValueError(f"invalid AppWorld task ID: {task_id!r}")
    return scenario


def select_resume_ids(
    task_ids: list[str], completed_ids: set[str], group_size: int
) -> list[str]:
    """Select missing tasks, expanding incomplete scenarios when required."""
    if group_size < 1:
        raise ValueError("group_size must be at least one")
    if group_size == 1:
        return [task_id for task_id in task_ids if task_id not in completed_ids]

    groups: OrderedDict[str, list[str]] = OrderedDict()
    for task_id in task_ids:
        groups.setdefault(scenario_id(task_id), []).append(task_id)

    selected: list[str] = []
    for scenario, members in groups.items():
        if len(members) != group_size:
            raise ValueError(
                f"scenario {scenario!r} has {len(members)} tasks; "
                f"expected {group_size}"
            )
        if any(task_id not in completed_ids for task_id in members):
            selected.extend(members)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--marker-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group-size", type=int, required=True)
    args = parser.parse_args()

    task_ids = args.dataset.read_text().split()
    completed_ids = {
        path.name[: -len("_data.json")]
        for path in args.marker_dir.glob("*_data.json")
    }
    selected = select_resume_ids(task_ids, completed_ids, args.group_size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(selected) + ("\n" if selected else ""))
    missing = sum(task_id not in completed_ids for task_id in task_ids)
    print(f"missing={missing} selected={len(selected)}")


if __name__ == "__main__":
    main()
