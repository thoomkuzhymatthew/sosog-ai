#!/usr/bin/env python3
"""Re-evaluate five official AppWorld outputs and require exact agreement."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    os.environ["APPWORLD_ROOT"] = str(args.root)
    from appworld import __version__, update_root
    from appworld.evaluator import evaluate_tasks

    update_root(str(args.root))
    output_root = args.root / "experiments" / "outputs"
    candidates = sorted(output_root.glob("**/evaluations/test_normal.json"))
    candidates += sorted(output_root.glob("**/evaluations/dev.json"))
    selected_path = None
    expected_report = None
    task_ids: list[str] = []
    for path in candidates:
        report = json.loads(path.read_text())
        experiment_dir = path.parents[1]
        compatible_ids = []
        for task_id in sorted(report.get("individual", {})):
            version_path = experiment_dir / "tasks" / task_id / "version" / "code.txt"
            if version_path.exists() and version_path.read_text().strip() == __version__:
                compatible_ids.append(task_id)
        if len(compatible_ids) >= 5:
            selected_path = path
            expected_report = report
            task_ids = compatible_ids[:5]
            break
    if selected_path is None or expected_report is None:
        raise SystemExit(
            f"no downloaded official evaluation has five outputs compatible with AppWorld {__version__}"
        )

    experiment_dir = selected_path.parents[1]
    experiment_name = str(experiment_dir.relative_to(output_root))
    actual_report = evaluate_tasks(
        task_ids=task_ids,
        experiment_name=experiment_name,
        suppress_errors=True,
        include_details=True,
        save_reports=False,
    )
    expected = {
        task_id: bool(expected_report["individual"][task_id]["success"])
        for task_id in task_ids
    }
    actual = {
        task_id: bool(actual_report["individual"][task_id]["success"])
        for task_id in task_ids
    }
    payload = {
        "schema_version": 1,
        "harness": "appworld",
        "appworld_version": __version__,
        "experiment_name": experiment_name,
        "task_ids": task_ids,
        "expected": expected,
        "actual": actual,
        "exact_match": actual == expected,
        "expected_passes": sum(expected.values()),
        "actual_passes": sum(actual.values()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    if actual != expected:
        raise SystemExit("AppWorld golden replay did not reproduce the official task scores")


if __name__ == "__main__":
    main()
