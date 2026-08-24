You are an isolated SOSOG coding worker extending Component 7 reporting. Read
`docs/REPAIR_LOOP_DESIGN.md`, Components 6 and 7 of
`docs/V1_ARCHITECTURE_PLAN.md`, all of `promotion_engine/reporting.py` and its
tests, and the public serialization contracts in `sosog/economics/` and
`sosog/repair/contracts.py` before editing.

Build a deterministic, defensive reporting extension:

1. Add `sosog/reporting/implementation_recommendation.py` with immutable,
   JSON-serializable recommendation contracts and a pure function deriving
   implementation options from the internal promotion action, whether client
   repo access is granted, and repair/review state. Cover API service, merge
   request, retained agentic path, human workflow, and collect-more-evidence.
   Repo access is necessary but not sufficient for a merge-request option; a
   human always chooses, and no recommendation may claim it has written,
   merged, approved, or deployed client code.
2. Extend `render_business_report` and `render_technical_report` through
   additive keyword-only arguments. Existing one-positional-argument callers
   and their exact safety semantics must remain valid. Accept serialized plain
   mappings/sequences for economics projections, fee breakdown, repair
   summaries, and implementation recommendations; do not require live DB or
   dataclass objects.
3. Replace the savings stub only when valid economics data is supplied.
   Clearly and separately label observed benchmark cost, projected claimed
   savings, scenario-only savings, realized savings (usually not supplied),
   and the SOSOG cost-plus fee. Never infer volume or savings from benchmark
   counts. Missing/malformed data must render as unavailable, never as zero or
   a guessed value. Unreviewed or rejected repair evidence must remain visibly
   bounded and cannot appear as realized savings.
4. Add deterministic repair-evidence and human-boundary sections. Do not print
   locked payloads, case IDs, expected values, or raw evaluator output; accept
   only summary fields/digests/counts.
5. Escape Markdown table input and sort task records deterministically.

Use dependency-free `unittest` tests. Cover backwards compatibility, complete
economics/fee rendering, unavailable/scenario/rejected evidence, explicit
realized savings only when supplied, implementation paths for every action,
repo-access gating, deterministic ordering, malformed inputs, and locked-data
non-rendering. Run the focused tests and full repository suite available in
the runtime.

Do not access network, credentials, database, or systemd. Do not change
economics, repair, persistence, architecture docs, or build-job files. Do not
commit, merge, push, or deploy. This is a proposal requiring independent
review.
