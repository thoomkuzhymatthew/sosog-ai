#!/usr/bin/env python3
"""Remove quota-failed mini-SWE predictions and emit a safe retry regex."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


RETRYABLE = re.compile(
    r"RateLimitError|ThrottlingException|Too many tokens|ServiceUnavailable",
    re.IGNORECASE,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--ids-output", type=Path, required=True)
    parser.add_argument("--only-ids", type=Path)
    args = parser.parse_args()
    allowed_ids = None
    if args.only_ids:
        allowed_ids = set(json.loads(args.only_ids.read_text()))
    predictions_path = args.output_dir / "preds.json"
    predictions = json.loads(predictions_path.read_text()) if predictions_path.exists() else {}
    retry_ids = []
    for path in sorted(args.output_dir.glob("*/*.traj.json")):
        data = json.loads(path.read_text())
        task_id = data.get("instance_id") or path.parent.name
        if allowed_ids is not None and task_id not in allowed_ids:
            continue
        blob = json.dumps(
            {
                "exit_status": data.get("info", {}).get("exit_status"),
                "exception": data.get("info", {}).get("exception_str"),
                "messages": data.get("messages", [])[-3:],
            },
            default=str,
        )
        if RETRYABLE.search(blob):
            retry_ids.append(task_id)
    retry_ids = sorted(set(retry_ids))
    for task_id in retry_ids:
        predictions.pop(task_id, None)
    if retry_ids:
        predictions_path.write_text(json.dumps(predictions, indent=2, sort_keys=True) + "\n")
    args.ids_output.parent.mkdir(parents=True, exist_ok=True)
    args.ids_output.write_text(json.dumps(retry_ids, indent=2) + "\n")
    print("^(" + "|".join(re.escape(task_id) for task_id in retry_ids) + ")$" if retry_ids else "")


if __name__ == "__main__":
    main()
