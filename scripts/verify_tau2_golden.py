#!/usr/bin/env python3
"""Re-evaluate a bounded slice of an official tau2 reference artifact."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--task-ids", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from tau2.data_model.simulation import Results
    from tau2.evaluator.evaluator import EvaluationType
    from tau2.scripts.evaluate_trajectories import compute_simulation_rewards

    raw = json.loads(args.reference.read_text())
    selected_ids = {str(item) for item in args.task_ids}
    selected = []
    seen = set()
    for simulation in raw["simulations"]:
        task_id = str(simulation["task_id"])
        if task_id in selected_ids and task_id not in seen:
            selected.append(simulation)
            seen.add(task_id)
    if seen != selected_ids:
        raise SystemExit(f"reference is missing task IDs: {sorted(selected_ids - seen)}")
    tasks = [task for task in raw["tasks"] if str(task["id"]) in selected_ids]
    expected = {
        str(item["task_id"]): {
            "reward": float(item["reward_info"]["reward"]),
            "reward_breakdown": item["reward_info"].get("reward_breakdown") or {},
        }
        for item in selected
    }
    subset = {**raw, "simulations": selected, "tasks": tasks}
    with tempfile.TemporaryDirectory(prefix="sosog-golden-") as directory:
        path = Path(directory) / "reference_subset.json"
        path.write_text(json.dumps(subset))
        results = Results.load(path)
        updated = compute_simulation_rewards(
            results=results,
            evaluation_type=EvaluationType.ALL,
            console=None,
            fresh_tasks=False,
        )
    actual = {
        str(item.task_id): {
            "reward": float(item.reward_info.reward),
            "reward_breakdown": {
                str(getattr(key, "value", key)): value
                for key, value in (item.reward_info.reward_breakdown or {}).items()
            },
        }
        for item in updated.simulations
    }
    mismatches = {
        task_id: {"expected": expected[task_id], "actual": actual.get(task_id)}
        for task_id in sorted(expected)
        if expected[task_id] != actual.get(task_id)
    }
    payload = {
        "schema_version": 1,
        "reference": str(args.reference),
        "task_ids": sorted(selected_ids, key=int),
        "expected": expected,
        "actual": actual,
        "mismatches": mismatches,
        "passed": not mismatches,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if mismatches:
        raise SystemExit(f"golden replay mismatch: {sorted(mismatches)}")
    print(f"golden replay passed for {len(selected_ids)} tasks")


if __name__ == "__main__":
    main()
