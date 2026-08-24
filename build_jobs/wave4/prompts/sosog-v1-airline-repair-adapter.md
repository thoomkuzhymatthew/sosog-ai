You are an isolated SOSOG coding worker converting the proven airline
flight-change evaluator into the first concrete vertical adapter for the
generic Component 4 repair library. Read `docs/REPAIR_LOOP_DESIGN.md`,
Component 4 of `docs/V1_ARCHITECTURE_PLAN.md`, all files in `sosog/repair/`,
`crystallized/airline/contracts.py`, and all of
`scripts/evaluate_airline_flight_change_repair.py` before editing. The generic
contracts and design doc are authoritative.

Build `crystallized/airline/flight_change_adapter.py` and refactor the existing
evaluation script into a thin compatibility CLI over it.

Requirements:

1. Implement the runtime-checkable `VerticalAdapter` protocol for one bound
   flight-change task family: payload-free, content-addressed visible and
   locked `SuiteManifest` values; `evaluate(candidate, tier)` returning exact
   `EvaluationReport` values; and historical cost. Preserve the current two
   real tau2 regression tasks and all current synthetic normal/unsafe cases.
2. A candidate location must be a regular non-symlink file whose SHA-256
   matches `CandidateReference.digest` before import. Use a unique import name
   per digest and reject modules without the expected executor contract.
3. Keep tau2 imports lazy so the locked synthetic suite and unit tests run
   without tau2 installed. Constructor dependencies/case runners should be
   injectable enough for tests; no network or live benchmark invocation in
   unit tests.
4. Locked payloads, expected results, and case IDs remain inside the adapter.
   The outward manifest contains only digest/tier/counts. Failed
   `CaseEvaluation` values expose only invariant categories, opaque failure
   fingerprints, and generic remediation-safe observations. Unsafe writes,
   writes before validation, duplicate/excess writes, and model calls must be
   safety violations where applicable.
5. Preserve the existing evaluator CLI arguments and legacy JSON/Markdown
   shape as far as practical, but make it delegate evaluation and rendering to
   the adapter rather than maintaining a second evaluator implementation.
6. Add dependency-free `unittest` coverage for exact manifest counts/digest
   determinism, candidate hash/symlink rejection, normal completion, unsafe
   deferral, wrong-write detection, model-call violation, locked feedback
   sanitization, and lazy tau imports. Use fake candidate modules/runners.

Do not expose locked suite content through a public method or serialized
manifest. Do not modify generic repair code, the candidate executor, policies,
economics, reporting, persistence, or orchestration. Do not access network,
credentials, database, or systemd. Do not commit, merge, push, or deploy. This
is a proposal requiring independent review and human safety review.
