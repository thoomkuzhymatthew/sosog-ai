#!/usr/bin/env python3
"""Append or verify hash-chained coding-job outcome evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from promotion_engine.outcomes import (
    append_outcome,
    verify_outcome_ledger,
)  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--record", type=Path, help="JSON object to append")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify == (args.record is not None):
        parser.error("choose exactly one of --record or --verify")
    if args.verify:
        records = verify_outcome_ledger(args.ledger)
        print(json.dumps({"records": len(records), "valid": True}, sort_keys=True))
        return
    value = json.loads(args.record.read_text())
    if not isinstance(value, dict):
        raise ValueError("record file must contain a JSON object")
    print(json.dumps(append_outcome(args.ledger, value), sort_keys=True))


if __name__ == "__main__":
    main()
