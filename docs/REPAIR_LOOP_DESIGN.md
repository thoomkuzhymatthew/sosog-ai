# SOSOG V1 Repair and Robustness Controller

This document freezes the contracts for Component 4 before implementation.
The existing airline flight-change repair is the reference instance, not the
generic architecture.

## Purpose and boundary

The controller turns one classified task family and an isolated candidate
artifact into auditable evidence. It may generate and repair proposals, but it
must never merge, deploy, or describe a candidate as production-approved. The
strongest successful terminal state is `PENDING_HUMAN_SAFETY_REVIEW`.

"Self-healing" means bounded search under an independent evaluator. It does
not mean repeatedly exposing hidden tests until an agent learns their answers.
The controller, not the repair model, decides whether evidence improved and
when further attempts are unjustified.

## Separation and leakage controls

Three roles remain separate:

1. The repair worker sees the task rubric, visible regression cases, allowed
   paths, and a sanitized failure summary from the previous attempt.
2. The locked evaluator owns normal-must-complete and
   unsafe-must-defer cases. It can load candidate artifacts but is never in a
   worker worktree and never contributes case payloads or expected answers to
   a worker prompt.
3. A human approves AI-drafted adversarial cases before they become locked and
   later performs the final safety review.

Every visible/locked manifest and candidate is content-addressed. The worker
can receive the visible suite, while the locked manifest exposed outside its
evaluator contains only a digest and case-class counts. The controller rejects
reports whose digest or counts differ from those frozen manifests. It persists
the full evaluator result for audit but passes only a
`RepairFeedback` object to the worker: aggregate scores, invariant categories,
opaque failure fingerprints, and remediation-safe observations. An explicit
test must prove that locked payloads, case IDs, expected values, and raw
failure output do not appear in serialized repair feedback.

## Generic interfaces

`sosog.repair.vertical_adapter.VerticalAdapter` supplies:

- a visible repair-suite manifest;
- a locked-suite manifest containing only counts/classes/digest outside the
  evaluator;
- evaluation of a content-addressed candidate at `VISIBLE` or `LOCKED` tier;
- conversion of an evaluation into sanitized feedback;
- historical baseline cost for the task family.

The evaluator returns structured `EvaluationReport` evidence. Case classes are
first-class: `REGRESSION`, `NORMAL_MUST_COMPLETE`, and
`UNSAFE_MUST_DEFER`. Safety violations include any write from a case that must
defer, writes before validation, excess/duplicate writes, permission escape,
or an evaluator-declared invariant breach.

A `RepairWorker` receives the best accepted candidate plus sanitized feedback
and returns a new content-addressed candidate. A production implementation can
bridge this protocol to the Codex dispatcher; tests use a deterministic fake.

## Improvement order

Candidate acceptance is lexicographic and fail-closed:

1. Fewer safety violations always wins. A candidate with more safety
   violations is never accepted regardless of aggregate pass count.
2. With equal safety, more locked unsafe cases passing wins.
3. Then more locked normal cases passing.
4. Then more visible regressions passing.
5. Then lower measured runtime cost, only when correctness scores tie.

The best accepted candidate is retained; the last attempted candidate is not
automatically the winner. A perfect locked score with zero safety violations
advances only to `PENDING_HUMAN_SAFETY_REVIEW`.

## Controller-owned inability to improve

The loop stops with explicit evidence when any condition is met:

- `STAGNATED`: no accepted score improvement for the configured window;
- `DUPLICATE_CANDIDATE`: a candidate digest repeats;
- `OSCILLATING`: candidate or failure fingerprints enter a repeated cycle;
- `REGRESSED_SAFETY`: an attempt introduces a new safety violation and the
  configured policy ends immediately;
- `ATTEMPT_LIMIT`, `COST_LIMIT`, or `TIME_LIMIT`;
- `EVALUATOR_BLOCKED`: evaluator infrastructure fails repeatedly, distinct
  from a candidate failing tests;
- `WORKER_BLOCKED`: proposal generation itself fails, distinct from a
  candidate or evaluator failure;
- `NO_SAFE_IMPROVEMENT`: repairs can increase ordinary pass rate only by
  weakening a safety invariant;
- `PENDING_HUMAN_SAFETY_REVIEW`: all automated gates pass.

All attempts, including rejected candidates and infrastructure failures, are
recorded. Repair budgets include model, worker, evaluator, and infrastructure
cost. A stop result includes the best candidate, score history, terminal
reason, unresolved failure categories, and next human action.

## Adversarial and stress evidence

The locked suite should cover policy boundaries, malformed/ambiguous intent,
wrong ownership, missing confirmation, unavailable state, unsupported payment
or action types, partial tool failures, retries, idempotency, duplicate writes,
timeouts, and representative valid variations. AI may draft cases from client
policy documents, but drafts remain `PENDING_HUMAN_APPROVAL`; approval freezes
the content hash. The repair worker never authors or edits its own evaluator.

## Persistence contract

The V1 operations migration adds append-only `proposals`, `repair_runs`,
`artifacts`, and `budget_events`, plus guarded pending-to-terminal decisions in
`review_items`. Proposals point to immutable artifacts. Every repair attempt
records candidate/feedback fingerprints,
structured score, terminal or attempt status, costs, and evidence. Automated
success creates a pending `HUMAN_SAFETY_REVIEW` item; it does not update a
deployment state.

## Economics and reporting interface

Economics consumes client-supplied versioned volume, measured current-agent
cost, classification, and repair evidence. It never substitutes benchmark
trace counts for production volume. Savings are emitted only with explicit
period, source, measured/estimated quality, fallback assumptions, and
confidence. Missing, failed, or rejected locked evidence makes automation
savings unavailable. Unreviewed locked evidence can be shown only as a
scenario and cannot be presented as realized savings.

Reporting receives serialized economics projections, repair summaries, and
implementation recommendations through additive keyword arguments. Existing
report callers remain valid. Reports must distinguish observed cost,
projected savings, realized savings, SOSOG fee, and the human-review boundary.
