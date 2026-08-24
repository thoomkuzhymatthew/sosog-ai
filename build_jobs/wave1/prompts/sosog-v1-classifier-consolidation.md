You are an isolated SOSOG coding worker building product infrastructure, not
a client-facing automation. This job is part of the SOSOG V1 rebuild
described in `docs/V1_ARCHITECTURE_PLAN.md` (component 3) — read that file's
"## 3. Classification engine (CONSOLIDATE)" section before starting for full
context, but the concrete task is scoped below.

Your current directory is a detached SOSOG Git worktree.

## Background

Two rule-based classifiers currently exist with hand-copied, near-duplicate
thresholds: `promotion_engine/classifier.py` (`build_promotion_plan`) and
`predictor/router_v0.py` (`predict`) + `predictor/labels.py`
(`automatic_label`). `promotion_engine/classifier.py` is the richer of the
two (it has a coverage gate, artifact/ambiguity gating, a no-write
`RESPONSE_CRYSTALLIZE` branch, and stable-prefix/volatile-tail decompose
detection that the other cascade lacks) and has already been chosen as the
one to keep. **Do not modify `promotion_engine/classifier.py` in this job —
it is correct as-is.**

Three existing scripts still import `predictor/router_v0.py` and
`predictor/labels.py` directly: `predictor/regret.py`,
`scripts/run_m17_predictor.py`, `scripts/run_m17_research_snapshot.py`. Do
not break these — they are milestone-17 research scripts staying on the old
modules deliberately, not being migrated in this job.

## Task

1. **`promotion_engine/taxonomy.py`** — a pure mapping function from the six
   internal `PromotionAction` values (defined in `promotion_engine/contracts.py`
   or wherever `build_promotion_plan` currently defines/imports them — read
   `promotion_engine/classifier.py` and `promotion_engine/contracts.py` first
   to find the exact enum/values) to four client-facing category strings:
   - `FULL_CRYSTALLIZE` and `RESPONSE_CRYSTALLIZE` → `FULLY_CRYSTALLIZABLE`
   - `DECOMPOSE` → `DECOMPOSABLE`
   - `LIFT` and `RETAIN` → `FULLY_AGENTIC`
   - `DROP` → `INSUFFICIENT_EVIDENCE` (its own bucket — do not fold this into
     `FULLY_AGENTIC` or `FULLY_MANUAL`; `DROP` means the corpus evidence was
     too poor to classify confidently, which is a data-quality outcome, not
     an automatability judgment)
   - Note: `FULLY_MANUAL` is never produced by this mapping — it's sourced
     from a separate client-declared manual-task registry elsewhere in the
     system (not built in this job). Don't add a case for it here; just
     document in a comment that it's intentionally absent from this mapping.
   - Keep the internal six-value action as the system of record everywhere
     else in the codebase; this mapping is for reporting/client-facing
     surfaces only.

2. **`promotion_engine/audit.py`** — port the non-duplicated audit/override
   machinery from `predictor/labels.py` (`apply_override`, `categorizer_audit`
   — read that file to find them) into this new module, adapted to operate on
   whatever candidate/result dict shape `promotion_engine/classifier.py`
   actually produces (read `build_promotion_plan`'s return shape) instead of
   `predictor/labels.py`'s `TaskLabel`. This becomes the mechanism for: (a)
   human overrides of an automatic classification, and (b) tracking
   agreement/disagreement between automatic and human-reviewed labels for
   calibration purposes. Preserve the original functions' behavior/semantics
   as closely as the different input shape allows — this is a port, not a
   redesign.

3. **`predictor/router_v0.py`** and **`predictor/labels.py`** — add a clear
   module-level docstring/comment marking these as legacy, research-only
   modules superseded by `promotion_engine/classifier.py` +
   `promotion_engine/taxonomy.py` for any new code path, and naming the three
   existing scripts that still depend on them. **Do not change any function
   behavior, signature, or logic in these two files** — this is a
   documentation-only change so future readers don't accidentally build new
   things on the superseded cascade.

## Constraints

- Do not modify `promotion_engine/classifier.py`, `promotion_engine/workflow.py`,
  `promotion_engine/reporting.py`, `predictor/features.py`, or
  `predictor/contracts.py`.
- Do not change any behavior in `predictor/router_v0.py` or
  `predictor/labels.py` — comments/docstrings only. Verify
  `predictor/regret.py`, `scripts/run_m17_predictor.py`, and
  `scripts/run_m17_research_snapshot.py` would still import and run
  unchanged (you don't need to run tau2/benchmark dependencies to verify
  this — just confirm the functions/classes they import still exist with the
  same signatures).

You may change exactly these paths:
- `promotion_engine/taxonomy.py`
- `promotion_engine/audit.py`
- `promotion_engine/tests/test_taxonomy.py`
- `promotion_engine/tests/test_audit.py`
- `predictor/router_v0.py`
- `predictor/labels.py`

The host will reject any other changed path, more than 6 changed files, or a
diff above 800000 bytes. Do not commit, merge, push, deploy, access
credentials, or enable network access.

Add focused tests covering: each `PromotionAction` → category mapping
(including `DROP` → `INSUFFICIENT_EVIDENCE`), the override/audit functions'
core behavior. Run the tests. In your final report: list changed files, test
commands run and their results, the exact shape of `build_promotion_plan`'s
output you adapted `audit.py` to (since the architecture doc didn't specify
it precisely), and any risks a human reviewer should check. Your work is a
proposal and cannot approve itself for merging.
