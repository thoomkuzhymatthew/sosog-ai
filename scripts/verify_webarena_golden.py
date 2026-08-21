#!/usr/bin/env python3
"""Require exact 3/3 scores from WebArena's official string evaluator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configs", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from browser_env.actions import create_stop_action
    from evaluation_harness.evaluators import StringEvaluator

    rows = json.loads(args.configs.read_text())
    candidates = [row for row in rows if row["eval"]["eval_types"] == ["string_match"]][:3]
    if len(candidates) != 3:
        raise SystemExit("three canonical string-match tasks were not found")
    details = []
    evaluator = StringEvaluator()
    for row in candidates:
        config = args.configs.parent / f"golden_{row['task_id']}.json"
        config.write_text(json.dumps(row, indent=2) + "\n")
        answer = row["eval"]["reference_answer_raw_annotation"]
        score = evaluator([create_stop_action(answer)], config)
        details.append({"task_id": row["task_id"], "expected": 1.0, "actual": score})
    payload = {
        "schema_version": 1,
        "harness": "WebArena official StringEvaluator",
        "rows": 3,
        "passes": sum(item["actual"] == item["expected"] for item in details),
        "exact_match": all(item["actual"] == item["expected"] for item in details),
        "details": details,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    if not payload["exact_match"]:
        raise SystemExit("WebArena evaluator golden replay failed")


if __name__ == "__main__":
    main()
