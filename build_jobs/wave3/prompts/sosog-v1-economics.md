You are an isolated SOSOG coding worker building Component 6 economics. Read
`docs/REPAIR_LOOP_DESIGN.md`, Component 6 of
`docs/V1_ARCHITECTURE_PLAN.md`, `promotion_engine/taxonomy.py`, and
`research_ops/budget.py`. Do not depend on sibling jobs: accept repair evidence
as validated plain mappings at this boundary.

Implement:

1. `sosog/economics/inputs.py`: immutable, validated, JSON-serializable
   versioned client-volume and cost-assumption records. Volume is supplied by
   the client with task_type, frequency, unit count, period, source and as-of
   date. Explicitly distinguish `MEASURED` and `ESTIMATED`; never infer volume
   from episode/benchmark counts.
2. `cost_model.py`: deterministic per-task projections and portfolio totals.
   Baseline is current agent cost × client volume. FULL/RESPONSE crystallize
   uses fixed automation cost plus locked-evaluation fallback rate × agent
   cost. DECOMPOSE uses prefix cost plus tail fraction × agent cost.
   FULLY_AGENTIC/FULLY_MANUAL/INSUFFICIENT_EVIDENCE produce zero claimed
   savings. Missing or invalid locked evidence must yield an unavailable or
   scenario-only projection, never a guessed dollar value. Each result carries
   period, formulas, assumptions, sources, quality, confidence, fallback rate,
   and whether savings are projected versus realized. Unreviewed repair
   evidence can be a clearly labeled scenario but not realized savings.
3. `fee.py`: aggregate recorded agent/infra costs and calculate cost plus a
   configurable markup defaulting to 10%. Validate nonnegative amounts and
   return a transparent breakdown; do not apply markup to customer savings.

Use Decimal internally for money and deterministic rounding/serialization.
Tests must cover every product category/action path, measured versus estimated
inputs, periods, missing evidence, fallback math, decomposed math, no-savings
categories, portfolio totals, markup, malformed inputs, and deterministic
output. No network/database. Do not modify reporting or persistence in this
job. Do not commit, merge, push, or deploy. Your result requires independent
review.
