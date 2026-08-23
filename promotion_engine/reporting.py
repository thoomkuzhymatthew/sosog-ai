"""Deterministic Markdown reports for promotion plans.

The renderers deliberately keep benchmark observations separate from commercial
projections.  A promotion plan contains evidence about benchmark runs; it does
not, by itself, contain the customer traffic needed to forecast savings.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

_ACTION_ORDER = (
    "FULL_CRYSTALLIZE",
    "RESPONSE_CRYSTALLIZE",
    "DECOMPOSE",
    "LIFT",
    "RETAIN",
    "DROP",
)


def _candidate_field(candidate: Mapping[str, Any], name: str, *aliases: str) -> Any:
    """Read both the flat public shape and the classifier's evidence object."""

    names = (name, *aliases)
    for key in names:
        if key in candidate:
            return candidate[key]

    evidence = candidate.get("evidence")
    if isinstance(evidence, Mapping):
        for key in names:
            if key in evidence:
                return evidence[key]
    return None


def _candidates(plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = plan.get("candidates", [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    candidates = [item for item in raw if isinstance(item, Mapping)]
    return sorted(candidates, key=lambda item: str(item.get("task_id", "")))


def _summary(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    value = plan.get("summary", {})
    return value if isinstance(value, Mapping) else {}


def _markdown_text(value: Any, *, default: str = "Not supplied") -> str:
    if value is None or value == "":
        return default
    return " ".join(str(value).split()).replace("|", "\\|")


def _format_count(value: Any) -> str:
    if value is None:
        return "Not supplied"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _markdown_text(value)
    return str(int(number)) if number.is_integer() else str(number)


def _format_rate(value: Any) -> str:
    if value is None:
        return "Not supplied"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _markdown_text(value)
    percentage = number * 100 if 0 <= number <= 1 else number
    return f"{percentage:.1f}%"


def _format_usd(value: Any) -> str:
    if value is None:
        return "Not supplied"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _markdown_text(value)
    return f"${number:,.6f}"


def _format_confidence(value: Any) -> str:
    if value is None:
        return "Not supplied"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _format_rate(value)
    return _markdown_text(value)


def _route_counts(
    summary: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]
) -> list[tuple[str, int]]:
    supplied = summary.get("action_counts")
    if not isinstance(supplied, Mapping):
        supplied = summary.get("route_counts")

    if isinstance(supplied, Mapping):
        counts: dict[str, int] = {}
        for action, count in supplied.items():
            try:
                counts[str(action)] = int(count)
            except (TypeError, ValueError):
                continue
    else:
        counts = dict(
            Counter(str(item.get("action", "UNCLASSIFIED")) for item in candidates)
        )

    ordered = [
        (action, counts.pop(action)) for action in _ACTION_ORDER if action in counts
    ]
    ordered.extend(sorted(counts.items()))
    return ordered


def _patterns(candidate: Mapping[str, Any]) -> str:
    value = _candidate_field(candidate, "write_name_patterns")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return "None recorded"
    patterns = sorted({_markdown_text(item) for item in value if item is not None})
    return ", ".join(patterns) if patterns else "None recorded"


def _review_status(candidate: Mapping[str, Any]) -> str:
    if candidate.get("promotion_review_required") is True:
        return "Required before promotion"
    required = _candidate_field(candidate, "review_required")
    if required is True:
        return "Required"
    if required is False:
        return "Not required by classification"
    return "Not supplied; treat as required"


def _observed_cost_lines(summary: Mapping[str, Any]) -> list[str]:
    labels = (
        ("observed_cost_usd", "Observed benchmark cost recorded by the plan"),
        ("candidate_cost_usd", "Observed candidate cost recorded by the plan"),
        ("mean_complete_cost_usd", "Observed mean cost per complete benchmark run"),
    )
    lines = [
        f"- {label}: **{_format_usd(summary[key])}**"
        for key, label in labels
        if key in summary
    ]
    if not lines:
        lines.append("- No aggregate observed benchmark cost was supplied.")
    return lines


def render_technical_report(plan: dict) -> str:
    """Render an evidence-focused technical promotion report."""

    summary = _summary(plan)
    candidates = _candidates(plan)
    vertical = _markdown_text(plan.get("vertical"), default="Unspecified")

    lines = [
        "# Technical Promotion Report",
        "",
        f"Vertical: **{vertical}**",
        "",
        "## Evidence",
        "",
        f"Candidates assessed: **{len(candidates)}**",
        "",
        "Costs below are observed benchmark measurements, not production savings projections.",
        "",
        "| Task | Pass rate | Actual runs | Mean observed cost/run | Confidence |",
        "| --- | ---: | ---: | ---: | --- |",
    ]

    if candidates:
        for candidate in candidates:
            lines.append(
                "| {task} | {rate} | {runs} | {cost} | {confidence} |".format(
                    task=_markdown_text(candidate.get("task_id")),
                    rate=_format_rate(_candidate_field(candidate, "pass_rate")),
                    runs=_format_count(_candidate_field(candidate, "actual_n", "n")),
                    cost=_format_usd(_candidate_field(candidate, "mean_cost_usd")),
                    confidence=_format_confidence(
                        _candidate_field(candidate, "confidence")
                    ),
                )
            )
    else:
        lines.append(
            "| No candidates | Not supplied | Not supplied | Not supplied | Not supplied |"
        )

    lines.extend(["", "### Aggregate benchmark cost fields", ""])
    lines.extend(_observed_cost_lines(summary))

    lines.extend(["", "## Routes", "", "| Route | Candidate count |", "| --- | ---: |"])
    route_counts = _route_counts(summary, candidates)
    if route_counts:
        lines.extend(
            f"| {_markdown_text(action)} | {count} |" for action, count in route_counts
        )
    else:
        lines.append("| No classified routes | 0 |")

    lines.extend(
        [
            "",
            "### Candidate rationale",
            "",
            "| Task | Route | Evidence-based reason |",
            "| --- | --- | --- |",
        ]
    )
    if candidates:
        for candidate in candidates:
            lines.append(
                f"| {_markdown_text(candidate.get('task_id'))} | "
                f"{_markdown_text(candidate.get('action'))} | "
                f"{_markdown_text(_candidate_field(candidate, 'reason'))} |"
            )
    else:
        lines.append("| No candidates | Not supplied | Not supplied |")

    lines.extend(
        [
            "",
            "## Safety and Review Boundaries",
            "",
            "Classifications are advisory. Held-out verification and the stated review boundary must pass before any generated change is promoted.",
            "",
            "| Task | Review boundary | Observed write-name patterns |",
            "| --- | --- | --- |",
        ]
    )
    if candidates:
        for candidate in candidates:
            lines.append(
                f"| {_markdown_text(candidate.get('task_id'))} | "
                f"{_review_status(candidate)} | {_patterns(candidate)} |"
            )
    else:
        lines.append("| No candidates | Review required | None recorded |")

    lines.extend(
        [
            "",
            "## Suggested Code-Change Stage",
            "",
            "Suggested stages are proposals only; generated changes should remain isolated until tests and review pass.",
            "",
        ]
    )
    if candidates:
        for candidate in candidates:
            task = _markdown_text(candidate.get("task_id"))
            action = _markdown_text(candidate.get("action"))
            stage = _markdown_text(_candidate_field(candidate, "proposed_next_stage"))
            lines.append(f"- **{task}** — `{action}`: {stage}")
    else:
        lines.append("- No code-change stage was proposed.")

    return "\n".join(lines) + "\n"


def render_business_report(plan: dict) -> str:
    """Render a business report without extrapolating unobserved savings."""

    summary = _summary(plan)
    candidates = _candidates(plan)
    vertical = _markdown_text(plan.get("vertical"), default="Unspecified")
    route_counts = _route_counts(summary, candidates)

    lines = [
        "# Business Promotion Report",
        "",
        f"Vertical: **{vertical}**",
        "",
        "## Decision Snapshot",
        "",
        f"The benchmark produced **{len(candidates)} candidate promotion decisions**.",
        "",
        "| Route | Candidate count |",
        "| --- | ---: |",
    ]
    if route_counts:
        lines.extend(
            f"| {_markdown_text(action)} | {count} |" for action, count in route_counts
        )
    else:
        lines.append("| No classified routes | 0 |")

    lines.extend(
        [
            "",
            "## Observed Benchmark Cost",
            "",
        ]
    )
    lines.extend(_observed_cost_lines(summary))
    lines.extend(
        [
            "",
            "These figures describe the measured benchmark only. They are not projected customer savings and are not annualised.",
            "",
            "| Task | Recommended route | Observed pass rate | Observed mean cost/run | Next evidence stage |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    if candidates:
        for candidate in candidates:
            lines.append(
                "| {task} | {action} | {rate} | {cost} | {stage} |".format(
                    task=_markdown_text(candidate.get("task_id")),
                    action=_markdown_text(candidate.get("action")),
                    rate=_format_rate(_candidate_field(candidate, "pass_rate")),
                    cost=_format_usd(_candidate_field(candidate, "mean_cost_usd")),
                    stage=_markdown_text(
                        _candidate_field(candidate, "proposed_next_stage")
                    ),
                )
            )
    else:
        lines.append(
            "| No candidates | Not supplied | Not supplied | Not supplied | Not supplied |"
        )

    lines.extend(
        [
            "",
            "## Customer Savings Projection",
            "",
            "**Not calculated.** A defensible projection requires customer workload volume, the production baseline cost, replacement-path cost, achieved quality, and fallback rate. None is inferred from benchmark route classifications.",
            "",
            "## Recommended Commercial Next Step",
            "",
            "Validate the proposed changes on held-out cases, then measure them in shadow traffic. Report customer savings only from the resulting production workload and cost measurements.",
        ]
    )

    return "\n".join(lines) + "\n"
