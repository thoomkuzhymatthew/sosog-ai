"""Deterministic Markdown reports for promotion plans.

The renderers deliberately keep benchmark observations separate from commercial
projections.  A promotion plan contains evidence about benchmark runs; it does
not, by itself, contain the customer traffic needed to forecast savings.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
import math
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
    return sorted(
        candidates,
        key=lambda item: (
            str(item.get("task_id", "")),
            str(item.get("action", "")),
            repr(sorted((str(k), repr(v)) for k, v in item.items())),
        ),
    )


def _summary(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    value = plan.get("summary", {})
    return value if isinstance(value, Mapping) else {}


def _markdown_text(value: Any, *, default: str = "Not supplied") -> str:
    if value is None or value == "":
        return default
    return (
        " ".join(str(value).split())
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "\\|")
    )


def _format_count(value: Any) -> str:
    if value is None:
        return "Not supplied"
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    if not math.isfinite(number) or number < 0:
        return "Unavailable"
    return str(int(number)) if number.is_integer() else str(number)


def _format_rate(value: Any) -> str:
    if value is None:
        return "Not supplied"
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    if not math.isfinite(number) or number < 0:
        return "Unavailable"
    percentage = number * 100 if 0 <= number <= 1 else number
    return f"{percentage:.1f}%"


def _format_usd(value: Any) -> str:
    if value is None:
        return "Not supplied"
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(Decimal(str(value)))
        if not math.isfinite(number) or number < 0:
            raise ValueError
    except (InvalidOperation, TypeError, ValueError):
        return "Unavailable"
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
                if isinstance(count, bool) or int(count) < 0:
                    raise ValueError
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


def _records(value: Any, *, nested: str | None = None) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if nested and isinstance(value.get(nested), Sequence) and not isinstance(value[nested], (str, bytes)):
            return [item for item in value[nested] if isinstance(item, Mapping)]
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _valid_money(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return number.is_finite() and number >= 0


def _decimal_value(value: Any) -> Decimal | None:
    return Decimal(str(value)) if _valid_money(value) else None


def _money_or_unavailable(value: Any) -> str:
    return _format_usd(value) if _valid_money(value) else "Unavailable"


def _text_sequence(value: Any) -> list[str] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    rows = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return rows if rows and len(rows) == len(value) else None


def _valid_projection(item: Mapping[str, Any], period: str) -> bool:
    availability = item.get("availability")
    if availability not in {"AVAILABLE", "SCENARIO_ONLY", "UNAVAILABLE"}:
        return False
    if not isinstance(item.get("task_type_id"), str) or not item["task_type_id"].strip():
        return False
    if item.get("period", period) != period:
        return False
    if item.get("quality") not in {"MEASURED", "ESTIMATED"}:
        return False
    try:
        confidence = Decimal(str(item.get("confidence")))
    except (InvalidOperation, TypeError, ValueError):
        return False
    if not confidence.is_finite() or not 0 <= confidence <= 1:
        return False
    if not isinstance(item.get("formula"), str) or not item["formula"].strip():
        return False
    if _text_sequence(item.get("sources")) is None:
        return False
    assumptions = item.get("assumptions")
    if not isinstance(assumptions, Sequence) or isinstance(assumptions, (str, bytes)):
        return False
    if any(not isinstance(value, str) or not value.strip() for value in assumptions):
        return False
    if not _valid_money(item.get("baseline_cost_usd")):
        return False
    if "reject" in str(item.get("reason") or "").lower() and availability != "UNAVAILABLE":
        return False
    if availability == "UNAVAILABLE":
        return (
            item.get("projected_cost_usd") is None
            and item.get("claimed_savings_usd") is None
        )
    projected = _decimal_value(item.get("projected_cost_usd"))
    claimed = _decimal_value(item.get("claimed_savings_usd"))
    baseline = _decimal_value(item.get("baseline_cost_usd"))
    if projected is None or claimed is None or baseline is None:
        return False
    return abs(claimed - max(Decimal("0"), baseline - projected)) <= Decimal("0.011")


def _realized_savings(value: Any, period: str) -> tuple[str, str]:
    if not isinstance(value, Mapping):
        return "Unavailable", "No measured realized-savings record was supplied."
    required = ("amount_usd", "source", "period", "as_of_date", "quality")
    if any(key not in value for key in required):
        return "Unavailable", "The realized-savings record is incomplete."
    try:
        date.fromisoformat(str(value.get("as_of_date")))
    except ValueError:
        return "Unavailable", "The realized-savings as-of date is invalid."
    if (
        not _valid_money(value.get("amount_usd"))
        or value.get("quality") != "MEASURED"
        or value.get("period") != period
        or not isinstance(value.get("source"), str)
        or not value["source"].strip()
        or not isinstance(value.get("as_of_date"), str)
        or not value["as_of_date"].strip()
    ):
        return "Unavailable", "The realized-savings record is not valid measured evidence."
    detail = (
        f"Measured source: {_markdown_text(value['source'])}; "
        f"as of {_markdown_text(value['as_of_date'])}."
    )
    return _format_usd(value["amount_usd"]), detail


def _economics_lines(value: Any) -> list[str] | None:
    records = _records(value, nested="tasks")
    container = value if isinstance(value, Mapping) else {}
    raw_period = container.get("period")
    if raw_period not in {"DAY", "WEEK", "MONTH", "QUARTER", "YEAR"} or not records:
        return None
    period_value = raw_period.strip()
    validity = [_valid_projection(item, period_value) for item in records]
    if not any(validity):
        return None
    totals_valid = all(validity) and all(
        _valid_money(container.get(key))
        for key in (
            "baseline_cost_usd", "projected_cost_usd",
            "claimed_savings_usd", "scenario_savings_usd",
        )
    )
    if totals_valid:
        baseline = _decimal_value(container.get("baseline_cost_usd"))
        projected = _decimal_value(container.get("projected_cost_usd"))
        claimed = _decimal_value(container.get("claimed_savings_usd"))
        totals_valid = abs(
            claimed - max(Decimal("0"), baseline - projected)
        ) <= Decimal("0.011")
    realized, realized_detail = _realized_savings(
        container.get("realized_savings"), period_value
    )
    period = _markdown_text(period_value)
    lines = [
        f"Period: **{period}**",
        "",
        "| Task | Availability | Evidence | Baseline cost | Projected cost | Projected claimed savings | Scenario-only savings | Fallback / assumptions | Sources |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    ordered = sorted(
        zip(records, validity),
        key=lambda pair: (
            str(pair[0].get("task_type_id", "")), str(pair[0].get("action", ""))
        ),
    )
    for item, item_valid in ordered:
        if not item_valid:
            lines.append(
                f"| {_markdown_text(item.get('task_type_id'))} | Unavailable | "
                "Unavailable | Unavailable | Unavailable | Unavailable | "
                "Unavailable | Unavailable | Unavailable |"
            )
            continue
        availability = item.get("availability")
        claimed = item.get("claimed_savings_usd") if availability == "AVAILABLE" else None
        scenario = item.get("claimed_savings_usd") if availability == "SCENARIO_ONLY" else None
        assumptions = list(item.get("assumptions", ()))
        if item.get("fallback_rate") is not None:
            assumptions.append(f"fallback_rate={item['fallback_rate']}")
        lines.append("| {task} | {availability} | {evidence} | {baseline} | {projected} | {claimed} | {scenario} | {assumptions} | {sources} |".format(
            task=_markdown_text(item.get("task_type_id")),
            availability=_markdown_text(availability, default="Unavailable"),
            evidence=(f"{_markdown_text(item.get('quality'))}; "
                      f"confidence {_format_rate(item.get('confidence'))}"),
            baseline=_money_or_unavailable(item.get("baseline_cost_usd")),
            projected=_money_or_unavailable(item.get("projected_cost_usd")),
            claimed=_money_or_unavailable(claimed), scenario=_money_or_unavailable(scenario),
            assumptions=", ".join(_markdown_text(value) for value in assumptions) or "None",
            sources=", ".join(_markdown_text(source) for source in item["sources"]),
        ))
    lines.extend([
        "",
        f"- Portfolio baseline cost: **{_money_or_unavailable(container.get('baseline_cost_usd')) if totals_valid else 'Unavailable'}**",
        f"- Portfolio projected cost: **{_money_or_unavailable(container.get('projected_cost_usd')) if totals_valid else 'Unavailable'}**",
        f"- Portfolio projected claimed savings: **{_money_or_unavailable(container.get('claimed_savings_usd')) if totals_valid else 'Unavailable'}**",
        f"- Portfolio scenario-only savings: **{_money_or_unavailable(container.get('scenario_savings_usd')) if totals_valid else 'Unavailable'}**",
        f"- Realized savings (measured evidence only): **{realized}**",
        f"- {realized_detail}",
        f"- Unavailable task count: **{_format_count(container.get('unavailable_task_count'))}**",
        "",
        "Scenario-only amounts rely on unreviewed evidence and are not projected claimed or realized savings. Rejected evidence cannot support a savings claim.",
    ])
    return lines


def _fee_lines(value: Any) -> list[str]:
    fee = value if isinstance(value, Mapping) else {}
    values = {
        key: _decimal_value(fee.get(key))
        for key in (
            "agent_cost_usd", "infrastructure_cost_usd", "recorded_cost_usd",
            "markup_rate", "markup_usd", "fee_usd",
        )
    }
    complete = all(item is not None for item in values.values())
    if complete:
        tolerance = Decimal("0.011")
        complete = (
            abs(values["recorded_cost_usd"] - (
                values["agent_cost_usd"] + values["infrastructure_cost_usd"]
            )) <= tolerance
            and abs(values["markup_usd"] - (
                values["recorded_cost_usd"] * values["markup_rate"]
            )) <= tolerance
            and abs(values["fee_usd"] - (
                values["recorded_cost_usd"] + values["markup_usd"]
            )) <= tolerance
        )
    rendered = fee if complete else {}
    return [
        "## SOSOG Cost-Plus Fee",
        "",
        "| Agent cost | Infrastructure cost | Recorded cost | Markup rate | Markup | SOSOG fee |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        "| {agent} | {infra} | {recorded} | {rate} | {markup} | {fee} |".format(
            agent=_money_or_unavailable(rendered.get("agent_cost_usd")),
            infra=_money_or_unavailable(rendered.get("infrastructure_cost_usd")),
            recorded=_money_or_unavailable(rendered.get("recorded_cost_usd")),
            rate=_format_rate(rendered.get("markup_rate")) if rendered else "Unavailable",
            markup=_money_or_unavailable(rendered.get("markup_usd")),
            fee=_money_or_unavailable(rendered.get("fee_usd")),
        ),
        "",
        ("The fee is separate from customer savings."
         if complete else
         "Fee breakdown unavailable: supplied cost-plus fields were incomplete or did not reconcile."),
    ]


def _repair_lines(value: Any) -> list[str]:
    records = _records(value)
    lines = [
        "## Repair Evidence",
        "",
        "Only aggregate summary fields, digests, and counts are shown; locked case contents and evaluator output are excluded.",
        "",
        "| Task | Tier | Status | Reviewed | Suite digest | Safety violations | Locked normal | Locked unsafe |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    allowed_statuses = {
        "STAGNATED", "DUPLICATE_CANDIDATE", "OSCILLATING",
        "REGRESSED_SAFETY", "ATTEMPT_LIMIT", "COST_LIMIT", "TIME_LIMIT",
        "EVALUATOR_BLOCKED", "WORKER_BLOCKED", "NO_SAFE_IMPROVEMENT",
        "PENDING_HUMAN_SAFETY_REVIEW", "APPROVED", "REJECTED",
    }
    for item in sorted(records, key=lambda row: (str(row.get("task_type_id", "")), str(row.get("suite_digest", "")))):
        score = item.get("best_score", item.get("score", {}))
        score = score if isinstance(score, Mapping) else {}
        normal = (f"{_format_count(score.get('locked_normal_passed'))}/"
                  f"{_format_count(score.get('locked_normal_total'))}")
        unsafe = (f"{_format_count(score.get('locked_unsafe_passed'))}/"
                  f"{_format_count(score.get('locked_unsafe_total'))}")
        status = item.get("status", item.get("stop_reason"))
        digest = item.get("suite_digest")
        digest_valid = (
            isinstance(digest, str) and len(digest) == 64
            and all(character in "0123456789abcdefABCDEF" for character in digest)
        )
        lines.append("| {task} | {tier} | {status} | {reviewed} | {digest} | {safety} | {normal} | {unsafe} |".format(
            task=_markdown_text(item.get("task_type_id")),
            tier=_markdown_text(item.get("tier")) if item.get("tier") == "LOCKED" else "Unavailable",
            status=_markdown_text(status) if status in allowed_statuses else "Unavailable",
            reviewed=_markdown_text(item.get("reviewed")) if type(item.get("reviewed")) is bool else "Unavailable",
            digest=_markdown_text(digest) if digest_valid else "Unavailable",
            safety=_format_count(score.get("safety_violations")), normal=normal, unsafe=unsafe,
        ))
    if not records:
        lines.append("| Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |")
    lines.extend(["", "A human safety reviewer must accept the evidence before any implementation or savings claim is treated as approved or realized."])
    return lines


def _implementation_lines(value: Any) -> list[str]:
    records = _records(value)
    lines = [
        "## Recommended Implementation Path",
        "",
        "These are options only. A human chooses and authorizes a path; no client code has been written, merged, approved, or deployed by this report.",
        "",
        "| Task | Action | Option | Eligible | Rationale | Prerequisites |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    rows = []
    allowed_paths = {
        "API_SERVICE", "MERGE_REQUEST", "RETAINED_AGENTIC",
        "HUMAN_WORKFLOW", "COLLECT_MORE_EVIDENCE",
    }
    for record in records:
        if record.get("human_decision_required") is not True:
            continue
        options = record.get("options")
        if not isinstance(options, Sequence) or isinstance(options, (str, bytes)):
            continue
        for option in options:
            prerequisites = option.get("prerequisites") if isinstance(option, Mapping) else None
            if (
                isinstance(option, Mapping)
                and option.get("path") in allowed_paths
                and type(option.get("eligible")) is bool
                and isinstance(option.get("rationale"), str)
                and option["rationale"].strip()
                and isinstance(prerequisites, Sequence)
                and not isinstance(prerequisites, (str, bytes))
                and all(isinstance(item, str) and item.strip() for item in prerequisites)
            ):
                rows.append((record, option))
    for record, option in sorted(rows, key=lambda pair: (
        str(pair[0].get("task_type_id", "")), str(pair[0].get("action", "")), str(pair[1].get("path", "")))):
        prereqs = option.get("prerequisites")
        prereq_text = ", ".join(sorted(_markdown_text(v) for v in prereqs)) if isinstance(prereqs, Sequence) and not isinstance(prereqs, (str, bytes)) else "None"
        lines.append(f"| {_markdown_text(record.get('task_type_id'))} | {_markdown_text(record.get('action'))} | {_markdown_text(option.get('path'))} | {_markdown_text(option.get('eligible'))} | {_markdown_text(option.get('rationale'))} | {prereq_text or 'None'} |")
    if not rows:
        lines.append("| Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |")
    return lines


def render_technical_report(
    plan: dict,
    *,
    economics_projections: Any = None,
    fee_breakdown: Any = None,
    repair_summaries: Any = None,
    implementation_recommendations: Any = None,
) -> str:
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

    if economics_projections is not None:
        lines.extend(["", "## Economics Projection", ""] + (_economics_lines(economics_projections) or ["Economics projection: **Unavailable** (missing or malformed input). "]))
    if fee_breakdown is not None:
        lines.extend([""] + _fee_lines(fee_breakdown))
    if repair_summaries is not None:
        lines.extend([""] + _repair_lines(repair_summaries))
    if implementation_recommendations is not None:
        lines.extend([""] + _implementation_lines(implementation_recommendations))
    return "\n".join(lines) + "\n"


def render_business_report(
    plan: dict,
    *,
    economics_projections: Any = None,
    fee_breakdown: Any = None,
    repair_summaries: Any = None,
    implementation_recommendations: Any = None,
) -> str:
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

    economics = _economics_lines(economics_projections)
    lines.extend(
        [
            "",
            "## Customer Savings Projection",
            "",
        ] + (economics or [
            "**Not calculated.** A defensible projection requires customer workload volume, the production baseline cost, replacement-path cost, achieved quality, and fallback rate. None is inferred from benchmark route classifications.",
        ]) + [
            "",
            "## Recommended Commercial Next Step",
            "",
            "Validate the proposed changes on held-out cases, then measure them in shadow traffic. Report customer savings only from the resulting production workload and cost measurements.",
        ]
    )

    if fee_breakdown is not None:
        lines.extend([""] + _fee_lines(fee_breakdown))
    if repair_summaries is not None:
        lines.extend([""] + _repair_lines(repair_summaries))
    if implementation_recommendations is not None:
        lines.extend([""] + _implementation_lines(implementation_recommendations))

    return "\n".join(lines) + "\n"
