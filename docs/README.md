# SOSOG documentation map

This page separates current product documentation from historical research.
Files in the research archive remain at their original paths to preserve
reproducibility and existing evidence references.

## Current product documentation

Read these in order:

1. [Accessible overview](SOSOG_ACCESSIBLE_BRIEF.md) — product thesis,
   workflow, safety model, economics, and what remains unproven.
2. [V1 architecture plan](V1_ARCHITECTURE_PLAN.md) — authoritative component
   design and current build-status table.
3. [Repair-loop design](REPAIR_LOOP_DESIGN.md) — bounded search, locked
   evaluation, stop conditions, and human-review boundary.
4. [Codex worker operations](codex_workers.md) — isolated EC2 job execution.
5. [External repository research brief](EXTERNAL_REPOSITORY_RESEARCH_BRIEF.md)
   — the next validation-source selection task.

`CTO_RECRUITING_BRIEF.md` is a current company/technical-leadership brief, not
an implementation specification.

## Research evidence archive

The evidence archive answers “why does SOSOG exist, and what has actually been
measured?” It does not supersede the V1 architecture.

- [Research archive index](research/README.md)
- [Consolidated findings](SOSOG_findings_report.md)
- [Latest cross-vertical investigation](vertical_investigation_progress_2026-08-22.md)
- `M0.md` through `M12.md` — Retail crystallization, safety, assistance,
  decomposition, and lifting experiments.
- `M17.md` — routing/predictor experiment.
- `metrics/` and `traces/` at the repository root — machine-readable evidence.

## Build provenance

`build_jobs/` contains the exact prompts and manifests used by isolated Codex
workers during the V1 rebuild. It is retained for auditability and should not
be mistaken for the product API.

## Documentation authority

When documents disagree:

1. The current-build-status table in `V1_ARCHITECTURE_PLAN.md` wins for what is
   implemented.
2. Code contracts and tests win for exact runtime behavior.
3. Milestone documents remain authoritative only for the experiment they
   record.
4. Commercial claims must retain the limitations stated in
   `SOSOG_ACCESSIBLE_BRIEF.md` and `SOSOG_findings_report.md`.
