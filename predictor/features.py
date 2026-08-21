"""Extract benchmark-neutral routing features from N-run JSONL traces.

The extractor deliberately knows nothing about benchmark evaluator internals.
Adapters only need to normalize tool calls into ``messages[*].tool_calls`` and
provide the set of mutating tool names (or mark calls with ``is_write``).
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .contracts import DivergencePoint, FailurePattern, TaskFeatures


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def task_id_for(run: dict[str, Any]) -> str:
    for key in ("task_id", "instance_id", "id"):
        if run.get(key) is not None:
            return str(run[key])
    raise ValueError("trace row is missing task_id/instance_id/id")


def run_passed(run: dict[str, Any]) -> bool:
    if "passed" in run:
        return bool(run["passed"])
    if "db_match" in run:
        return bool(run["db_match"])
    reward_info = run.get("reward_info") or {}
    db_check = reward_info.get("db_check") or {}
    if "db_match" in db_check:
        return bool(db_check["db_match"])
    if "reward" in reward_info:
        return float(reward_info.get("reward") or 0.0) >= 1.0
    return float(run.get("reward") or 0.0) >= 1.0


def calls_for(run: dict[str, Any], write_tools: set[str]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    if isinstance(run.get("calls"), list):
        sources: Iterable[dict[str, Any]] = run["calls"]
    else:
        sources = (
            call
            for message in run.get("messages") or []
            for call in (message.get("tool_calls") or [])
        )
    for call in sources:
        name = str(call.get("name") or call.get("tool_name") or "")
        if not name:
            continue
        arguments = call.get("arguments")
        if arguments is None:
            arguments = call.get("args") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        calls.append(
            {
                "name": name,
                "arguments": arguments,
                "is_write": bool(call.get("is_write", name in write_tools)),
                "signature": f"{name}({canonical(arguments)})",
            }
        )
    return calls


def common_prefix(sequences: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    if not sequences:
        return []
    result: list[dict[str, Any]] = []
    for values in zip(*sequences):
        signatures = {item["signature"] for item in values}
        if len(signatures) != 1:
            break
        result.append(values[0])
    return result


def read_prefix_and_boundary(
    sequences: list[list[dict[str, Any]]],
) -> tuple[int, bool, int]:
    raw_prefix = common_prefix(sequences)
    safe_len = 0
    for call in raw_prefix:
        if call["is_write"]:
            break
        safe_len += 1

    next_calls = [seq[safe_len] for seq in sequences if len(seq) > safe_len]
    boundary_is_write = bool(next_calls) and all(call["is_write"] for call in next_calls)
    return safe_len, boundary_is_write, len(raw_prefix)


def skeleton(calls: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(call["signature"] for call in calls if call["is_write"])


def write_variance(passing_calls: list[list[dict[str, Any]]]) -> dict[str, Any]:
    skeletons = [skeleton(calls) for calls in passing_calls]
    name_orders = [
        tuple(call["name"] for call in calls if call["is_write"])
        for calls in passing_calls
    ]
    args_by_name: dict[str, set[str]] = defaultdict(set)
    for calls in passing_calls:
        for call in calls:
            if call["is_write"]:
                args_by_name[call["name"]].add(canonical(call["arguments"]))
    varying_tools = sorted(name for name, args in args_by_name.items() if len(args) > 1)
    return {
        "distinct_passing_write_skeletons": len(set(skeletons)),
        "write_order_varies": len(set(name_orders)) > 1,
        "argument_values_vary": bool(varying_tools),
        "tools_with_argument_variance": varying_tools,
    }


def explicit_artifact_signal(runs: list[dict[str, Any]]) -> tuple[bool, bool]:
    annotations = [run.get("annotations") or {} for run in runs]
    artifact = any(
        bool(run.get("artifact_flag"))
        or bool(note.get("artifact"))
        or bool(note.get("verifier_artifact"))
        or bool(note.get("simulator_disagreement"))
        for run, note in zip(runs, annotations)
    )
    ambiguous = any(
        bool(run.get("ambiguity_signal")) or bool(note.get("ambiguous"))
        for run, note in zip(runs, annotations)
    )
    return artifact, ambiguous


def categorize_failure_pattern(
    runs: list[dict[str, Any]], sequences: list[list[dict[str, Any]]]
) -> str:
    artifact, ambiguous = explicit_artifact_signal(runs)
    if artifact or ambiguous:
        return FailurePattern.ARTIFACT.value

    passing = [seq for run, seq in zip(runs, sequences) if run_passed(run)]
    failed = [seq for run, seq in zip(runs, sequences) if not run_passed(run)]
    if not failed:
        if len({skeleton(seq) for seq in passing}) > 1:
            return FailurePattern.VOLATILE_TAIL.value
        return FailurePattern.NOT_APPLICABLE.value

    passing_skeletons = {skeleton(seq) for seq in passing}
    failed_skeletons = {skeleton(seq) for seq in failed}
    failed_write_skeletons = {item for item in failed_skeletons if item}

    safe_len, _, _ = read_prefix_and_boundary(sequences)
    stable_read_prefix = safe_len > 0
    if len(failed_write_skeletons) == 1 and not (
        failed_write_skeletons & passing_skeletons
    ):
        return FailurePattern.AGENT_WANDERED.value
    if stable_read_prefix and (
        len(passing_skeletons) > 1 or len(failed_skeletons) > 1
    ):
        return FailurePattern.VOLATILE_TAIL.value
    if len(failed_skeletons) > 1:
        return FailurePattern.MIXED.value
    return FailurePattern.NEEDS_REVIEW.value


def extract_task_features(
    vertical: str,
    task_id: str,
    runs: list[dict[str, Any]],
    *,
    write_tools: set[str],
    baseline_cost: float = 0.0,
) -> TaskFeatures:
    if not runs:
        raise ValueError(f"task {task_id} has no runs")
    sequences = [calls_for(run, write_tools) for run in runs]
    passed = [run_passed(run) for run in runs]
    passing_calls = [seq for ok, seq in zip(passed, sequences) if ok]
    passing_skeletons = {skeleton(seq) for seq in passing_calls}
    safe_len, before_write, raw_lcp_len = read_prefix_and_boundary(sequences)

    if all(seq == sequences[0] for seq in sequences[1:]):
        divergence = DivergencePoint.NONE.value
    else:
        median_len = statistics.median((len(seq) for seq in sequences)) or 1
        divergence = (
            DivergencePoint.LATE.value
            if raw_lcp_len >= median_len / 2 or before_write
            else DivergencePoint.EARLY.value
        )
    artifact, ambiguous = explicit_artifact_signal(runs)
    return TaskFeatures(
        vertical=vertical,
        task_id=str(task_id),
        pass_rate=sum(passed) / len(runs),
        actual_n=len(runs),
        distinct_passing_skeletons=len(passing_skeletons),
        longest_common_read_prefix_len=safe_len,
        prefix_ends_before_write=before_write,
        write_arg_variance_across_passes=write_variance(passing_calls),
        first_diverge_point=divergence,
        failure_pattern=categorize_failure_pattern(runs, sequences),
        artifact_flag=artifact,
        ambiguity_signal=ambiguous,
        m2_baseline_cost=float(baseline_cost),
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: invalid JSON: {exc}") from exc
    return rows


def extract_corpus_features(
    vertical: str,
    rows: list[dict[str, Any]],
    *,
    write_tools: set[str],
    baseline_costs: dict[str, float] | None = None,
) -> list[TaskFeatures]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[task_id_for(row)].append(row)
    baseline_costs = baseline_costs or {}
    return [
        extract_task_features(
            vertical,
            task_id,
            grouped[task_id],
            write_tools=write_tools,
            baseline_cost=baseline_costs.get(task_id, 0.0),
        )
        for task_id in sorted(grouped, key=lambda item: (not item.isdigit(), int(item) if item.isdigit() else item))
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_jsonl", type=Path)
    parser.add_argument("--vertical", required=True)
    parser.add_argument("--write-tools", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    write_data = json.loads(args.write_tools.read_text())
    write_tools = set(write_data.get("write_tools", write_data))
    payload = {
        "schema_version": 1,
        "vertical": args.vertical,
        "features": [
            feature.to_dict()
            for feature in extract_corpus_features(
                args.vertical, read_jsonl(args.trace_jsonl), write_tools=write_tools
            )
        ],
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
