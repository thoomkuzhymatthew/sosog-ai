#!/usr/bin/env python3
"""Persist one normalized run/task row to the S3-first research store."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_ops.persistence import ResearchStore, StoreConfig  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("run", "task-run"))
    parser.add_argument("json_file", type=Path)
    args = parser.parse_args()
    value = json.loads(args.json_file.read_text())
    store = ResearchStore(StoreConfig.from_env())
    if args.kind == "run":
        store.record_run(value)
        print("stored run manifest")
    else:
        result = store.record_task_run(value)
        print(result["s3_uri"])


if __name__ == "__main__":
    main()
