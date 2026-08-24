You are an isolated SOSOG coding worker building the generic Component 4
repair/robustness library. Read `docs/REPAIR_LOOP_DESIGN.md` completely, then
read Component 4 of `docs/V1_ARCHITECTURE_PLAN.md`,
`crystallized/airline/contracts.py`,
`scripts/evaluate_airline_flight_change_repair.py`,
`scripts/run_airline_flight_change_repair_controller.sh`, and the current
`sosog/orchestration/controller.py`. The design document is authoritative if
older reference code differs.

Implement a dependency-injected, deterministic core. This is product
infrastructure, not an airline-specific rewrite and not an autonomous deployer.

Requirements:

1. `sosog/repair/contracts.py`: validated, JSON-serializable enums/dataclasses
   for candidate references, evaluation tiers/case classes, structured scores,
   evaluation reports, sanitized repair feedback, attempt records, controller
   policy, stop reasons, and the terminal loop result. Candidate and feedback
   fingerprints must be deterministic. The best possible state is
   `PENDING_HUMAN_SAFETY_REVIEW`, never deployed/merged.
2. `vertical_adapter.py`: runtime-checkable Protocol(s) for the locked evaluator
   and repair worker. Locked payloads/expected answers must not be present in a
   feedback object or worker-facing serialization.
3. `evaluator.py`: score comparison and report-to-feedback sanitization.
   Acceptance is the lexicographic order frozen in the design: safety first,
   then unsafe locked cases, normal locked cases, visible regressions, and cost
   only as a final tie breaker. Evaluator infrastructure failure is distinct
   from a candidate test failure.
4. `controller.py`: a synchronous `run_repair_loop(...)` over injected fakeable
   evaluator/worker interfaces. Retain the best accepted candidate, not the
   last attempt. Detect duplicate candidates, score stagnation, candidate or
   feedback oscillation, safety regression, attempt/cost/time limits,
   evaluator failure limits, no-safe-improvement, and perfect automated
   evidence. Persist/emit every attempt through an optional recorder callback.
   Never expose a locked report directly to the repair worker.
5. `case_drafting.py`: one injectable Bedrock Haiku call that drafts normal and
   unsafe adversarial cases from policy text. Strictly parse/validate JSON and
   return `PENDING_HUMAN_APPROVAL`; it must not create a locked manifest.
6. Replace the orchestration controller stub with the bounded single-worker
   supervisor described by its docstring. Make systemd/process/time/filesystem
   operations injectable or thin enough for tests. It must require a passed
   circuit breaker and freeze only explicitly allowed, regular, non-symlink
   files below the worktree. No live systemd call in tests.

Tests must cover: perfect advance only to human review; plateau/stagnation;
duplicate candidate; two-state oscillation; safety regression rejection;
best-candidate retention; attempt/cost/time caps; repeated evaluator
infrastructure failure; score ordering; feedback fingerprint determinism;
an explicit leakage test showing locked case payload/IDs/expected answers do
not occur in worker feedback; malformed case-draft responses; and supervisor
path/symlink/circuit-breaker validation.

Do not access the network, credentials, live systemd, or database. Do not
modify the airline reference, evaluator, tests, policy, classifier, ingestion,
or persistence code. Do not commit, merge, push, or deploy. Your result is a
proposal requiring independent review.
