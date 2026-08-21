#!/usr/bin/env python3
"""Update a per-instance model-route map from mini-SWE-agent outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("route_map", type=Path)
    parser.add_argument("model")
    parser.add_argument("--only", type=Path)
    args = parser.parse_args()
    predictions = json.loads(args.predictions.read_text()) if args.predictions.exists() else {}
    routes = json.loads(args.route_map.read_text()) if args.route_map.exists() else {}
    only = None
    if args.only:
        only = set(json.loads(args.only.read_text()))
    for task_id in predictions:
        if only is None or task_id in only:
            routes[task_id] = args.model
    args.route_map.parent.mkdir(parents=True, exist_ok=True)
    args.route_map.write_text(json.dumps(routes, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
