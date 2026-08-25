# Research evidence archive

This is the index for SOSOG's pre-V1 and cross-vertical investigation record.
The underlying files intentionally remain in `docs/`, `metrics/`, and
`traces/` so their original commands and references continue to work.

## Evidence sequence

| Phase | Documents | Question |
|---|---|---|
| Baseline and trace corpus | `M0.md`–`M3.md` | Can repeated agent behavior be measured consistently? |
| Deterministic crystallization | `M4.md`–`M5_5.md` | Can selected stable work be executed without another model call? |
| Parsing and safety gates | `M6.md`–`M8.md` | Can the system resolve inputs, refuse unsafe cases, and partly automate generation? |
| Assistance/decomposition/lifting | `M10.md`–`M12.md` | What should happen when full crystallization is inappropriate? |
| Cross-vertical routing | `M17.md`, `vertical_investigation_progress_2026-08-22.md` | Do useful intervention boundaries transfer beyond one family? |

Supporting documents:

- `SOSOG_findings_report.md` — consolidated evidence and limitations.
- `M3_partial.md` and `M3_flaky_analysis.md` — intermediate corpus and
  instability analysis.
- `M5_feasibility.md` and `M8_recipe.md` — implementation feasibility and
  automation recipe.
- `probe_failures.md` — negative and failed probes retained to prevent
  survivorship bias.

## Evidence locations

- `metrics/` — structured experiment summaries and promotion plans.
- `traces/` — trace exports used by the measured experiments.
- `scripts/` — historical run and evaluation harnesses.
- `config/` — frozen task selections and experiment inputs.
- `patches/` — upstream benchmark reproduction patches.

These paths are relative to the repository root, despite this index living
under `docs/research/`.

## Interpretation rules

- Benchmark pass rates are evidence about the measured task set, not customer
  production rates.
- Zero-model execution cost excludes integration, evaluation, maintenance,
  fallback, and human-review cost unless a document explicitly includes them.
- A successful generated proposal is not approved for deployment until it
  passes independent review.
- Negative results and manual-work boundaries are product evidence, not
  cleanup targets.
