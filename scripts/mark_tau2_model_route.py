#!/usr/bin/env python3
"""Assign a model route to newly completed tau2 checkpoint rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def key_for(item: dict) -> str:
    return f"{item.get('task_id')}:{item.get('trial', 0)}:{item.get('seed', 0)}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("route")
    parser.add_argument("route_map", type=Path)
    args = parser.parse_args()
    data = json.loads(args.results.read_text())
    route_map = json.loads(args.route_map.read_text()) if args.route_map.exists() else {}
    assigned = 0
    for simulation in data.get("simulations", []):
        if simulation.get("termination_reason") == "infrastructure_error":
            continue
        key = key_for(simulation)
        if key not in route_map:
            route_map[key] = args.route
            assigned += 1
    args.route_map.parent.mkdir(parents=True, exist_ok=True)
    args.route_map.write_text(json.dumps(route_map, indent=2, sort_keys=True) + "\n")
    print(f"assigned {assigned} completed rows to {args.route}")


if __name__ == "__main__":
    main()
