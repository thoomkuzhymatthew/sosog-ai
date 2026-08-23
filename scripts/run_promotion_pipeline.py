#!/usr/bin/env python3
"""Classify trace evidence and emit coding jobs plus reviewable reports."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from promotion_engine.classifier import build_promotion_plan  # noqa: E402
from promotion_engine.reporting import (  # noqa: E402
    render_business_report,
    render_technical_report,
)
from promotion_engine.workflow import build_coding_jobs, enrich_plan  # noqa: E402


def _json_lines(lines: Iterable[str], source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{source}:{number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{source}:{number}: each JSONL row must be an object")
        rows.append(value)
    return rows


def load_trace_rows(source: str) -> list[dict[str, Any]]:
    """Load a local or S3 JSONL trace without changing its evidence."""

    if source.startswith("s3://"):
        parsed = urlparse(source)
        if not parsed.netloc or not parsed.path.lstrip("/"):
            raise ValueError(f"invalid S3 trace URI: {source}")
        try:
            import boto3
        except ModuleNotFoundError:
            try:
                result = subprocess.run(
                    ["aws", "s3", "cp", source, "-"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "S3 input requires either boto3 or the AWS CLI"
                ) from exc
            except subprocess.CalledProcessError as exc:
                detail = exc.stderr.strip() or "AWS CLI returned no error detail"
                raise RuntimeError(f"could not read {source}: {detail}") from exc
            return _json_lines(result.stdout.splitlines(), source)
        else:
            response = boto3.client("s3").get_object(
                Bucket=parsed.netloc,
                Key=parsed.path.lstrip("/"),
            )
            lines = (
                value.decode("utf-8") for value in response["Body"].iter_lines()
            )
            return _json_lines(lines, source)
    path = Path(source)
    return _json_lines(path.read_text().splitlines(), str(path))


def load_write_tools(path: Path) -> set[str]:
    value = json.loads(path.read_text())
    values = value.get("write_tools", value) if isinstance(value, dict) else value
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ValueError("write-tools config must be a string list or {write_tools: [...]}")
    return set(values)


def write_outputs(
    output_dir: Path,
    plan: dict[str, Any],
    jobs: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "promotion_plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "technical_report.md").write_text(render_technical_report(plan))
    (output_dir / "business_report.md").write_text(render_business_report(plan))
    jobs_dir = output_dir / "coding_jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    public_jobs = []
    for job in jobs:
        prompt_path = jobs_dir / f"{job['job_id']}.md"
        prompt_path.write_text(job["prompt"] + "\n")
        public_jobs.append({key: value for key, value in job.items() if key != "prompt"})
    (jobs_dir / "jobs.json").write_text(
        json.dumps(public_jobs, indent=2, sort_keys=True) + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_jsonl", help="local path or s3:// URI")
    parser.add_argument("--vertical", required=True)
    parser.add_argument("--write-tools", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repository", default=str(ROOT))
    parser.add_argument("--min-complete-runs", type=int, default=5)
    parser.add_argument("--max-coding-jobs", type=int, default=3)
    args = parser.parse_args()

    rows = load_trace_rows(args.trace_jsonl)
    raw_plan = build_promotion_plan(
        args.vertical,
        rows,
        write_tools=load_write_tools(args.write_tools),
        min_complete_runs=args.min_complete_runs,
    )
    plan = enrich_plan(raw_plan)
    jobs = build_coding_jobs(
        plan,
        repository=args.repository,
        max_jobs=args.max_coding_jobs,
    )
    plan["summary"]["coding_jobs_emitted"] = len(jobs)
    write_outputs(args.output_dir, plan, jobs)
    print(
        json.dumps(
            {
                "vertical": args.vertical,
                "candidates": len(plan.get("candidates", [])),
                "coding_jobs": len(jobs),
                "output_dir": str(args.output_dir),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
