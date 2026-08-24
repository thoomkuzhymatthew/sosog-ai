# SOSOG V1 Target Architecture & Refactor Plan

Written 2026-08-24 after auditing the existing research codebase
(predictor/, promotion_engine/, research_ops/, infra/aws/, crystallized/,
metrics/, traces/) against the V1 product pipeline below. **If you're picking
this up in a new session, read "Current build status" first — it's kept up
to date and tells you exactly what's real, what's proposed-but-unmerged, and
what to do next.**

## Current build status (update this section as work lands)

Two separate tracks exist — don't conflate them:
1. **Airline flight-change repair loop** (older, pre-V1-rebuild work) —
   passed all tests (13/13, zero wrong writes, zero model calls), status:
   `ADVANCE_TO_HUMAN_SAFETY_REVIEW`. Not part of the rebuild below.
2. **This rebuild** (Wave 1 onward) — status as of 2026-08-24:

| Item | Status |
|---|---|
| Job 1 — persistence (`002_sosog_v1.sql`, `sosog/persistence/store.py`) | **Merged**, commit `f7c9c3cea1972f5cf9a830d88e31a71876a3eeb8` |
| Job 2 — classifier consolidation (`taxonomy.py`, `audit.py`) | **Merged**, same commit |
| Job 3 — orchestration substrate + Codex auth-refresh fix | **Merged**, same commit |
| Follow-ups — classifier audit validation/source + auth-blocked resume | **Merged**, with Wave 2 ingestion in commit `0efd3df8b4bf57b0a3901611b90a4116c97640a1` |
| Wave 2 — generic ingestion/redaction/artifact pipeline | **Merged**, same commit; independent review added structural-field redaction protection and atomic pre-persistence validation |
| `sosog_v1` database | Migrations `002`–`004` applied over TLS. Component 4/10 tables (`artifacts`, `proposals`, `repair_runs`, `budget_events`, `review_items`) and guarded review decisions were live-smoke-tested; secure runtime config is `/etc/sosog/v1.env` |
| EC2 Python runtime | `/opt/sosog/runtime-venv` has the exact pinned V1 dependency set; rebuildable bootstrap landed in commit `a788a52d8de7466af7924bd53054af44e3a64888` |
| Wave 2b — task clustering + outcome judge (`build_jobs/wave2b/`, 2 concurrent jobs) | **Merged**, commit `b3e655c0f1671011e4721e541031e8995d18c616`; independent review added input, model-selection, and persistence-failure validation |
| Component 9 — worker-trace adapter + end-to-end dogfood runner | **Merged**, commit `fe951af33f87c359b94e0d08ac2945f25dd83b9f`; live run persisted 38 episodes, 6 task types, and 6 classifications |
| Component 4 — bounded repair/self-healing core | **Merged**, commits `c3a1307d556e9ced23ddd7b45e502aa4b1a6caf6`, `7186e15b95734f95430d907c3ca25c0480269294`, and `128dfff0446de9ee0ecc728522eb8ee12586d8a2`; includes locked/visible suite contracts, safety-first scoring, bounded stop reasons, case drafting, Codex worker bridge, and the airline adapter |
| Component 6 — economics + cost-plus fee | **Merged**, commit `c3a1307d556e9ced23ddd7b45e502aa4b1a6caf6`; projections require client volume and reviewed locked evidence, distinguish measured/estimated/scenario-only, and never infer realized savings |
| Component 7 — business/technical reporting | **Merged**, commit `7186e15b95734f95430d907c3ca25c0480269294`; renders economics/fee contracts, aggregate-only repair evidence, and human-authorized implementation options |
| Remaining product components | Component 8 event-triggered re-investigation and Component 11's thin review console are not built. Real external repository validation can begin before those two components are complete |

Every `build_jobs/waveN*/` directory launches with its own script
(`launch_*.sh <BASE_COMMIT_SHA>`) once its prerequisites are merged — see the
"Before handing this to Codex to execute" section below for the pattern.

1. Identify business tasks from client trace records.
2. Normalize + classify each task: FULLY_CRYSTALLIZABLE / DECOMPOSABLE /
   FULLY_AGENTIC / FULLY_MANUAL.
3. Robustness-test each proposed solution; self-heal (generate → test → repair →
   re-test) against a locked held-out set the repairing worker never sees.
4. Estimate $ savings from client task volume.
5. Produce business + technical reports, including an implementation-path
   recommendation (API service vs. merge request vs. other).
6. Event-triggered re-investigation on codebase changes or new client info,
   gated by human sign-off before re-entering the pipeline.
7. Meta-trace SOSOG's own workers through the same pipeline.
8. Commercial layer: agent cost + 10% markup, accurate cost tracking.

Two decisions are already made and drive every component below:
- **Postgres is canonical for V1.** A new database is created on the existing
  DB instance (EC2 runtime configuration is in `/etc/sosog/v1.env`), separate from the old
  `sosog_research` research schema. All planned tables get real read+write
  persistence, not the current write-only, two-of-six-tables state.
- **Single-engagement for V1.** No multi-tenant isolation logic yet, but every
  table gets an `engagement_id` column now so adding real isolation later isn't
  a retrofit across unindexed historical rows.

## Package layout

Keep `predictor/` and `promotion_engine/` in place — they're proven, tested,
and are the classification spine. Add one new top-level package, `sosog/`, for
everything that doesn't exist yet (ingestion, task identification, repair-loop
generalization, orchestration dispatcher/controller, economics,
re-investigation, the new persistence layer). `sosog/` imports from
`predictor`/`promotion_engine`; never the other direction. Confirm this before
coding starts — it's the one structural decision everything else assumes.

---

## 1. Trace ingestion & normalization (NEW)

**Gap:** nothing today accepts an arbitrary client trace export. Every current
consumer assumes tau-bench/AppWorld/SWE-bench-shaped rows (`task_id`,
`messages[*].tool_calls`, a `passed`/`reward` field).

**Critical bug to fix before any client data flows through:**
`predictor/features.py:run_passed()` falls through to
`float(reward or 0.0) >= 1.0` when no known success field is present — a row
with no ground-truth label silently reads as a **failed** run, not "unknown."
Safe for benchmarks (every row has a reward); would quietly wreck `pass_rate`
on real client data, which usually has no oracle at all.

**Resolved: LLM-judged outcome labeling closes the gap** (see component 2 —
the judge needs the cluster-level task rubric that stage produces, so it runs
right after clustering, not inside ingestion itself). Ingestion's job is just
to leave `success_source="unknown"` honestly unset rather than guessing.
`success_source` becomes a ranked-trust field, not a flag:
`programmatic_verifier` (best — a deterministic check like tau-bench's DB-state
match, when one exists) > `client_label` (human-provided ground truth, when
the client has any) > `llm_judged` (new, see component 2) > `unknown`
(excluded from pass-rate math with a visible "insufficient evidence" reason,
never silently counted as failure).

**Build:**
- `sosog/ingestion/schema.py` — versioned `NormalizedEpisode`: task_type_id
  (nullable until stage 2 runs), timestamps, `calls[]`, `outcome{status,
  success: bool|None, success_source, confidence: float|None}`,
  `cost{usd, tokens, model}`, `annotations`, `raw_ref`.
- `sosog/ingestion/adapters/generic_mapped.py` — one config-driven adapter
  (mapping file, same pattern as `config/airline_write_tools.json`) rather than
  speculative bespoke adapters for formats no client has sent yet.
- `sosog/ingestion/pipeline.py` — raw export → immutable artifact → adapter →
  validate → persist via component 10.
- `sosog/ingestion/redaction.py` — strips/tokenizes sensitive fields (customer
  names, emails, payment details) out of call arguments/results **before**
  anything is persisted or reaches the normalized schema. Config-driven per
  client, same mapping-file pattern as the adapter above — this, not a
  managed-analytics service, is the right fix for "client doesn't want to
  hand over raw sensitive data": the pipeline needs real row-level access to
  do its job (cluster, judge, generate fixes), so protection has to happen at
  the door, not by restricting what the pipeline itself can see.

Manual (no-agent) tasks have no traces to cluster from — they need a separate
client-provided task inventory, captured as a companion "manual task registry."

---

## 2. Business-task identification (PARTIALLY NEW)

Fully automated, closed-loop — no blocking human step. The safety-critical
gate in this system belongs later (`HUMAN_SAFETY_REVIEW` before any live
automation ships, component 4); a wrong cluster here only produces a slightly
inaccurate report line item, not an unsafe write, so blocking the pipeline on
a human here would cost the closed-loop property for no real safety benefit.

**Build:**
- `sosog/task_identification/embed.py` — one embedding call per trace (Bedrock
  Titan or Cohere embeddings, alongside the existing `BEDROCK_HAIKU_MODEL_ID`/
  `BEDROCK_SONNET_MODEL_ID` setup in `.env`) over the initial request/trace
  summary. Embeddings, not a full completion call, are the cheap primitive
  here — O(n) calls, ~10-100x cheaper than a completion, purpose-built for
  clustering.
- `sosog/task_identification/cluster.py` — two-stage clustering: (1) coarse
  partition by write-call skeleton + read-tool multiset, reusing
  `predictor/features.py:calls_for`/`skeleton` unchanged (free, catches
  "different tools entirely"); (2) within each skeleton bucket, **HDBSCAN**
  on the embedding vectors for the initial batch (catches "same tools,
  different business intent") — chosen over agglomerative-with-cutoff
  because it handles clusters of varying tightness and has native outlier
  detection (a genuinely one-off trace gets excluded rather than forced into
  a spurious tiny "task type"), and over fixed-K k-means because the number
  of business task types is unknown upfront and grows over time. Requires
  adding `hdbscan` to whatever bootstraps the Python environment these
  Codex workers run in (same pattern as `bootstrap_appworld.sh`'s pinned
  dependencies). It is installed ahead of time in the live EC2 runtime,
  outside the network-disabled sandbox; the exact set is now pinned in
  `infra/aws/requirements-v1-runtime.txt` and installed by
  `infra/aws/bootstrap_v1_runtime.sh`. For **ongoing** assignment (new traces
  arriving later, or component 8's re-investigation deciding "is this an
  existing task or a new one"), don't reload the fitted HDBSCAN model —
  keep it cheap and stateless: nearest-centroid-with-threshold against the
  centroids HDBSCAN already found in the batch step. One algorithm for
  finding the task types, a simpler one for checking against them later.
- `sosog/task_identification/label.py` — one cheap Haiku call **per accepted
  cluster** (not per trace — keeps LLM calls at O(task types), not O(traces))
  summarizing its example traces into a task name + description for the
  report.
- `sosog/task_identification/outcome_judge.py` — **the success-oracle
  answer.** One Haiku-tier Type B call **per episode**, given that episode's
  calls/result plus its cluster's rubric (the name + description `label.py`
  just generated) — outputs `{success: bool, confidence: float, rationale}`,
  written back onto the episode as `success_source="llm_judged"`. O(episodes),
  not O(task types) — the bigger cost line in this stage, but still Haiku-tier,
  no tool use, and far cheaper than the agent run that produced the trace in
  the first place. **Calibration, not blind trust:** sample a fraction of
  `llm_judged` episodes into the same human spot-check/override flow as
  `review.py` below (reuses `promotion_engine/audit.py`'s ported
  `categorizer_audit` mechanism from component 3 — the judge itself gets
  audited, not just cluster assignment). Sample rate is an open decision (see
  bottom of doc). When a client *does* have any ground-truth labels, those
  should populate `success_source="client_label"` and skip the judge entirely
  for that episode — the judge only fills gaps, never overrides real evidence.
- `sosog/task_identification/review.py` — async correction only, not a gate:
  same override-file convention as `predictor/labels.py:apply_override`. A
  human can merge/split/rename a cluster after the fact and the correction
  feeds back in, but nothing in the pipeline waits on it. Produces the
  `task_types` table.

---

## 3. Classification engine (CONSOLIDATE)

**Keep:** `predictor/features.py` and `predictor/contracts.py` — vertical-agnostic,
already the right shared foundation.

**Consolidate onto `promotion_engine/classifier.py`, not the predictor
cascade** — it's the richer of the two duplicated classifiers (coverage gate,
artifact/ambiguity gating, the no-write `RESPONSE_CRYSTALLIZE` branch, and
stable-prefix/volatile-tail decompose detection that `predictor/router_v0.py`
lacks).

- **Retire** `predictor/router_v0.py` and `predictor/labels.py:automatic_label`
  (duplicate, strictly weaker cascade). Its crude `SAVINGS_FACTORS` table is
  superseded outright by component 6's real cost model.
- **Port, don't retire**, `labels.py`'s audit/override machinery
  (`apply_override`, `categorizer_audit`) into `promotion_engine/audit.py`.
- **Migration required, not a clean deletion:** `predictor/regret.py`,
  `scripts/run_m17_predictor.py`, and `scripts/run_m17_research_snapshot.py`
  all import `router_v0`/`labels` directly. Leave them on the old modules under
  an explicit `# LEGACY, research-only` note rather than rewriting research
  history — but decide this consciously.
- **Build** `promotion_engine/taxonomy.py` — maps the six internal
  `PromotionAction` values to the four client-facing categories
  (`FULL_CRYSTALLIZE`/`RESPONSE_CRYSTALLIZE` → FULLY_CRYSTALLIZABLE;
  `DECOMPOSE` → DECOMPOSABLE; `LIFT`/`RETAIN` → FULLY_AGENTIC; plus
  FULLY_MANUAL sourced from component 2's manual registry). Keep the internal
  6-value action as the system of record; the 4-value taxonomy is reporting-only.

**Open decision:** what does `DROP` (today: "corpus evidence too poor to act
on") mean on a client report? Probably its own bucket ("insufficient evidence —
human review recommended"), not silently folded into FULLY_AGENTIC or
FULLY_MANUAL.

This component depends on component 2's outcome-judge output, not just
`task_type_id` — its cascade thresholds need real `success`/`success_source`
values, and `unknown`-labeled episodes stay excluded from pass-rate math
regardless of source. Consider weighting or requiring a higher evidence bar
(larger `n`, or a confidence floor) for `llm_judged` episodes vs.
`programmatic_verifier`/`client_label` ones, since they carry more inherent
noise — an open calibration question, not a blocker.

---

## 4. Proposal generation + robustness/self-healing loop (GENERALIZE)

**Keep as-is:** `crystallized/airline/contracts.py` (`ExecutionStatus`,
`ToolClient`, `ExecutionResult`) — treat as the contract any future vertical
executor implements, not an airline-only artifact. Also keep
`promotion_engine/workflow.py`'s escalation ladder
(`INDEPENDENT_HELD_OUT → ADVERSARIAL_DEFERRAL → HUMAN_SAFETY_REVIEW →
SHADOW_ECONOMICS`) and `outcomes.py`'s stage list — already generic.

**Historical context:** the original airline flight-change repair was a
template, not a library — hardcoded task IDs, hardcoded tau2 imports, a hand-built
`synthetic_cases()` fixture generator, a hardcoded frozen-proposal path. Split
into:
- `sosog/repair/vertical_adapter.py` (Protocol) — `load_repair_cases()`,
  `load_locked_cases()` (with `normal_must_complete`/`unsafe_must_defer` kept
  as first-class types — that's the actual safety contract), `run_case(...)`,
  `historical_cost_for(...)`. `crystallized/airline/flight_change_adapter.py`
  becomes the first concrete implementation, extracted from
  `evaluate_airline_flight_change_repair.py`.
- `sosog/repair/controller.py` — the family-parameterized version of
  `run_airline_flight_change_repair_controller.sh`, as a Python library
  function, not a new bash script per experiment.
- `sosog/repair/evaluator.py` — the generic two-tier repair/locked runner and
  decision logic, taking a `vertical_adapter` instead of hardcoded imports.
- `evaluate_airline_flight_change_repair.py` and its controller script become
  thin CLI entry points calling into `sosog/repair/`.
- `sosog/repair/case_drafting.py` — **decided:** don't leave locked-case
  authorship as pure manual work per client per task family (that's the
  bottleneck below). One Type B call drafts candidate adversarial + normal
  cases from the client's stated policy docs/rules for that task family, using
  the airline suite's shape as the template (a mix of "must safely refuse"
  cases — insufficient funds, wrong owner, ambiguous input, missing
  confirmation — and "must complete correctly" cases). A human reviews and
  approves the draft before anything is locked — drafting is automatable,
  confirming what "unsafe" actually means for this client's real rules is not,
  since it defines correctness for a write-action, not just a report line.

**Implemented:** `sosog/repair/` now supplies the generic contracts, evaluator,
bounded controller, case-drafting boundary, and Codex repair-worker bridge.
`crystallized/airline/flight_change_adapter.py` is the first concrete adapter;
the former evaluation script is now a compatibility CLI. The controller
retains the best safe candidate and stops explicitly on stagnation, duplicate
or oscillating proposals, safety regression, repeated unsafe trade-offs,
evaluator/worker blockage, or attempt/cost/time limits. A perfect automated
score advances only to `PENDING_HUMAN_SAFETY_REVIEW`, never to merge/deploy.
The concrete adapter was rerun on EC2 against the independently frozen airline
proposal and real tau2 harness: 2/2 visible regressions, 4/4 locked normal
cases, and 7/7 locked unsafe cases passed with zero wrong writes/model calls.

**Open risks:**
- Case-drafting quality depends entirely on how complete/clear the client's
  policy documentation is — thin or ambiguous docs mean a thinner draft, more
  for the human reviewer to fill in by hand. Not a blocker, but sets
  expectations: this reduces the manual work, it doesn't remove it.
- The "worker never sees the locked set" guarantee currently rests on
  file-system/process isolation. Turning this into a shared library makes it
  easier to accidentally leak locked-case data into a prompt-construction path
  also used for visible cases. Needs an explicit test invariant, not just
  discipline.

---

## 5. Job/worker orchestration substrate

### Agent/worker taxonomy

Only two fundamentally different call types exist across every component
above — the design should not invent more, and should not reach for a
third-party agent framework (LangChain/LangGraph/CrewAI/etc.) for either of
them. LangChain solves in-process agent-loop construction (tool routing,
memory, multi-step chains); that's not the gap here. Codex CLI already is a
complete agent loop for Type A, and Type B is single-shot/few-tool-call, where
a raw Bedrock Converse API call is simpler and has no framework version churn
to manage. The actual gap is the dispatcher below, which is plain Python.

| Type | Used by | Model/tool | Sandbox needs |
|---|---|---|---|
| **A — Coding agent** | Repair/crystallization proposal generation (component 4); possibly deep codebase impact assessment (component 8) | Codex CLI, full tool-use loop | Heavy — worktree, Landlock/bwrap, `require_changes: true`, `allowed_changed_paths` |
| **B — Single-shot model call** | Cluster auto-labeling (component 2), trigger-note parsing (component 8), report narrative bits | Bedrock Claude (Haiku/Sonnet, already configured) | None — no worktree, no filesystem, direct API call |

Type B never touches the Codex job/worker infra at all — no queue file, no
systemd unit, no sandbox. Treating a single completion call as a "worker job"
would be over-engineering; it's just a function call from inside pipeline code.

**Keep entirely as-is:** `infra/aws/run_codex_agent.sh` and
`codex-agent@.service` — manifest validation, attempt numbering,
Landlock/bwrap sandboxing, circuit breakers, full evidence trail. This is
already generic; every Type A job above can use it unmodified with a different
manifest/prompt.

**Build:**
- `sosog/orchestration/dispatcher.py` — generalizes
  `infra/aws/launch_codex_family_jobs.sh` (today hardcoded to one `jobs.json`,
  asserts exactly 3 jobs) into `enqueue_jobs(jobs, agent_root, repo,
  base_commit)`, same safety checks, arbitrary job count/caller.
- `sosog/orchestration/controller.py` — the shared controller library
  described in component 4.

**Resume-timer collapse:** the three near-identical
`sosog-m1{3,4,5}-*-resume.service/.timer` pairs differ only in status-file
path, unit name, and a timer offset. Collapse to one `%i`-templated
`sosog-resume@.service`/`.timer` pair (same pattern as the existing
`sosog-track@.service`/`install_track_service.sh`), offset passed at install
time or replaced with `RandomizedDelaySec`.

### Codex OAuth session-expiry fix

Root cause: `install_codex_runtime.sh` installs a Codex CLI authenticated via
interactive `codex login` (OAuth, sourced from
`/home/ubuntu/.codex/packages/standalone/current`), and `run_codex_agent.sh`
invokes `codex exec --sandbox {read-only|workspace-write}` with no writable-root
override. Codex's own workspace-write sandbox restricts filesystem writes to
the worktree tree — it does not include `~/.codex/auth.json`, which lives
outside it. Any in-sandbox token refresh therefore likely can't persist back
to disk, so the on-disk token ages until it hard-expires and never
self-recovers. This tracks with the hardening added in `71b20e5`/`e2efaff`/
`4b06cee` landing immediately before the failure was first observed. Switching
to `OPENAI_API_KEY` auth would sidestep this entirely but moves billing from
the (cheaper, already-owned) ChatGPT-plan subscription to metered pay-per-token
— ruled out on cost grounds. Fix instead by keeping OAuth and running the
refresh outside the sandbox:

- **`sosog-codex-auth-refresh.service`/`.timer`** (own systemd pair, `%i`-free
  since there's one Codex login for the whole host) — `OnUnitActiveSec=12h`,
  `OnBootSec=5m`. Runs as `ubuntu`, **unsandboxed** (no `--sandbox` flag at
  all — safe, since it only runs the CLI's own trusted auth logic, not
  agent-generated code): triggers Codex's token refresh/validation, letting
  the write-back to `~/.codex/auth.json` succeed outside the sandbox. Writes
  `{"status":"valid"|"blocked_auth","checked_at":...}` atomically to
  `agent_root/auth-status.json`. On `blocked_auth` (refresh token hit its
  absolute hard cap, needs a human to re-login), does not retry-loop —
  retrying can't fix a dead refresh token.
- **Centralizing the refresh in one timer, not per-worker,** also avoids a
  correctness bug, not just duplication: most OAuth providers rotate the
  refresh token on every use (old one invalidated once a new one issues). Up
  to 3 concurrent workers each attempting their own refresh could race and
  invalidate each other's session. One source of truth avoids this outright.
- **Worker preflight:** `run_codex_agent.sh` reads `auth-status.json` before
  starting the `codex exec` timeout block. If `blocked_auth` (or the file is
  missing/stale past ~13h, meaning the refresh timer itself is down), the
  worker exits immediately into a `blocked_auth` job status instead of
  consuming a slot for hours only to hit a 401 partway through — queue and
  worktree untouched, mirroring the existing `blocked_usage` handling.
- **Graceful resume:** when the refresh timer flips `blocked_auth` → `valid`
  (its own next successful 12h tick, or immediately after a human re-login —
  see below), it scans `agent_root/jobs/*/status` for anything in
  `blocked_auth` and does `systemctl start codex-agent@<job_id>.service` for
  each. Reuses the same generic resume-timer pattern as the vertical resume
  collapse above, with "auth recovered" as the trigger instead of "daily quota
  reset."
- **Instant resume on manual login:** the 12h timer alone would leave up to a
  12-hour gap after a human completes `codex login`. Ship a one-line wrapper,
  e.g. `/usr/local/libexec/sosog/codex_login_and_resume.sh`:
  `codex login && sudo systemctl start sosog-codex-auth-refresh.service` — one
  terminal command, refresh-check runs on demand instead of waiting for its
  timer, resume follows within seconds.
- The absolute-hard-cap case (human must re-login) can't be automated away —
  it's inherent to OAuth. This design just makes it rare, predictable, and
  non-destructive to queued work, instead of a random mid-job failure.

---

## 6. Cost/savings estimation from client volume (NEW)

**Historical gap (implemented):** `promotion_engine/reporting.py` previously
had only a literal `"Not calculated."` savings stub.

**Implemented:**
- `sosog/economics/inputs.py` — client-provided volume as its own versioned
  artifact: `{task_type_id, frequency, unit_count, source, as_of_date}`.
  Explicitly *not* derived from benchmark trace counts — it's collected from
  the client separately.
- `sosog/economics/cost_model.py` — per task_type:
  `baseline_cost = current_agent_cost * volume`; post-automation cost per
  classification (crystallizable → near-zero + fallback_rate × agent_cost,
  using component 4's locked-eval failure rate, not a guess; decomposable →
  prefix_cost + tail_fraction × agent_cost, reusing
  `predictor/features.py:read_prefix_and_boundary`; agentic/manual → no
  savings, reported for narrative completeness). Every number ships with its
  quality/fallback assumptions inline — never a bare dollar figure.
- `sosog/economics/fee.py` — agent/infra cost + 10% markup, mostly a query
  over component 10's `budget_events` table plus the markup formula.

**Open decision:** what replacement-cost assumption to use before any client
pilot exists — the report needs to clearly distinguish "measured" vs.
"estimated" savings, same discipline the current report already applies.

---

## 7. Reporting (EXTEND)

**Keep:** `promotion_engine/reporting.py` — genuinely generic, deterministic,
defensive about missing inputs. Extend, don't replace.

**Implemented:**
- Replaced the "Not calculated" savings stub with validated output from component 6.
- New "Recommended Implementation Path" section
  (`sosog/reporting/implementation_recommendation.py`) — derives API-service
  vs. merge-request vs. other from classification action + whether the client
  has granted repo access. Should propose options with rationale; a human
  picks, given a merge-request path implies write access to a client's
  production repo.
- Both new sections are additive keyword args on the existing render
  functions — existing callers keep working unchanged.

---

## 8. Event-triggered re-investigation (NEW)

**Build:**
- `sosog/reinvestigation/trigger_intake.py` — accepts a codebase diff or
  free-text notes, normalizes into an immutable `TriggerEvent` before any
  processing (same "evidence first" discipline as `ResearchStore`).
- `sosog/reinvestigation/impact_assessment.py` — a bounded Codex worker job
  (reuses component 5 unchanged) that assesses which existing automations a
  trigger might invalidate, produces a structured `ImpactReport`. Manifest sets
  `require_changes: false` — this job never writes code, only a report.
- `sosog/reinvestigation/signoff.py` — human gate; `ImpactReport` sits in
  `PENDING_HUMAN_SIGNOFF` until explicitly approved, only then re-enters
  classification (component 3) for the affected task_type.

**Open decision:** free-text meeting-notes intake implies an LLM read of
unstructured text — confirm this is in scope for V1 or should stub to
manual-triage logging only.

---

## 9. Meta-tracing SOSOG's own workers (MOSTLY WIRING)

`run_codex_agent.sh`'s evidence trail (`trace.jsonl`, `events.jsonl`,
`usage_events`) is already exactly the shape component 1 expects. Build one
more adapter, `sosog/ingestion/adapters/sosog_worker_trace.py`, mapping worker
actions onto `NormalizedEpisode.calls[]` with `vertical="sosog_internal"`. No
changes needed to the classifier or feature extraction — point stages 2/3 at
it like any other vertical. Lowest priority; matches the expectation that this
yields little since audit logic should be vertical-agnostic.

**Implemented and live-tested:** `sosog_worker_trace.py` archives the raw
trace first, then persists only aggregated/redacted worker actions (never raw
commands, command output, agent prose, or EC2 paths). `sosog/dogfood.py` and
`scripts/run_sosog_worker_trace_dogfood.py` connect ingestion, Titan
embeddings, HDBSCAN, Haiku cluster labels, outcome handling, classification,
and Postgres persistence. The first run processed 38 real airline-family
worker attempts: 35 episodes linked into six task types, three remained
HDBSCAN noise, and six classifications were persisted. The result correctly
separated the 35 failed attempts into three `DROP` clusters and the three
successful but under-covered attempts into three `RETAIN` clusters. Database
readback confirmed TLS, no orphan classifications, and no persisted raw
command/output/path fields; all 38 raw artifacts are mode `0600`.

---

## 10. Persistence / data model

**Gap:** `research_ops/persistence.py:ResearchStore` is write-only,
implements 2 of 6 planned tables, and `infra/aws/sql/001_sosog_research.sql`
is research-shaped (`subject_model`, `harness_name` NOT NULL — no client-
engagement equivalent).

**Build:** `infra/aws/sql/002_sosog_v1.sql`, a new database (`sosog_v1` or
similar — needs a concrete name + env-var convention alongside the existing
`DB_NAME`) on the existing instance:

- `episodes` — replaces `task_runs`'s research-only shape; no NOT NULL
  research fields, optional `metadata jsonb` instead.
- `task_types` (component 2).
- `classifications` — merges `task_features` + `router_predictions` into one
  table, since V1 has one classifier, not a router-plus-features split.
- `proposals` / `repair_runs` (component 4) — captures the escalation-ladder
  stage.
- `artifacts` — kept close to existing shape, already generic.
- `budget_events` — kept close to existing shape, add `job_id`/`episode_id`
  FK options for the fee calculation's episode-level granularity.
- **Every table gets `engagement_id text NOT NULL DEFAULT 'default'` now** —
  cheap to add today, expensive to retrofit across 6 unindexed tables later.

`sosog/persistence/store.py` replaces `ResearchStore` with real read+write
methods across all tables; every component above goes through it, none touch
flat JSON/JSONL or raw SQL directly. Keeps `ResearchStore`'s
immutable-artifact-then-DB-upsert crash-safety ordering.

`research_ops/budget.py:BudgetGuard` stays as-is — a fast, crash-safe,
sub-millisecond local cap check a DB round-trip can't replace — but each
`record()` call also best-effort-enqueues a `budget_events` row so the SQL
table stays the reporting source of truth while the flock ledger stays the
enforcement source of truth.

**Open decisions:** exact new DB name + env-var convention; whether
`classifications`/`proposals` are append-only history or upsert-latest
(append-only fits re-investigation's re-classify use case better, and matches
`outcomes.py`'s existing hash-chained ledger philosophy).

---

## 11. Human review console (NEW, decided)

Every point in the pipeline that genuinely needs a human — not a capability
gap, a trust/independent-check requirement — becomes a row in the DB
(component 10) with a pending status once that component exists:
`HUMAN_SAFETY_REVIEW` (component 4, before any automation goes live),
re-investigation sign-off (component 8), the outcome-judge calibration sample
(component 2), adversarial-case-draft approval (component 4), and the
implementation-path/savings-confidence judgment calls (components 6/7). A
small internal staff tool listing these with enough context to act is low
effort once persistence exists, and is the actual product surface for the
"AI proposes, human approves, nothing ships without sign-off" governance story
— worth having even at solo-founder scale, not just once there's a team.

**Build:**
- `sosog/review_console/` — a thin CRUD layer over component 10's pending-review
  rows: list, open one item with its full context (the trace, the proposed
  automation, the judge's confidence, the drafted test cases — whatever's
  relevant to that row type), approve/reject/edit, write back.
- Internal-only, not client-facing. Simple login (not a public signup flow —
  it's just you, for now). Host at a subdomain, e.g. `console.authoreate.com`.
- No elaborate UI investment for V1 — a list and a detail view with an
  approve/reject button covers every job type in category A/B/C above.
- **Auth-status shortcut** (fixes a real gap — the Codex OAuth login shortcut
  had no home): a prominent status indicator reading `auth-status.json`
  (component 5) plus a copy-paste-ready re-login command when it's
  `blocked_auth`. Guaranteed to work — build this first. A fully one-click
  version (dashboard triggers the login itself) depends on whether Codex
  CLI's OAuth flow can be completed on a different device than the one
  running it (device-code style) vs. requiring a browser on the EC2 box
  itself (local-callback style) — verify which one Codex CLI actually does
  before promising the one-click version; don't assume.

**Depends on:** component 10 (needs real rows to show) and at least one of the
review-gate components existing to populate it — natural to build once
component 4's `HUMAN_SAFETY_REVIEW` stage is wired up, since that's the
highest-stakes gate.

---

## Build order — waves, not a strict sequence

The existing infra already runs up to 3 Codex workers concurrently
(`CODEX_AGENT_MAX_CONCURRENCY=3`), and three components have zero dependency
on each other — so the real plan is waves of parallel jobs, not one job after
another. Each job in a wave must touch non-overlapping paths (already true of
the split below) since the manifest circuit breaker enforces
`allowed_changed_paths` per job.

- **Wave 1 (3 concurrent):** Component 10 narrow (`episodes`/`task_types`/
  `classifications` schema + store) · Component 3 (classifier consolidation,
  validated against existing benchmark JSONL in the interim) · Component 5
  (orchestration substrate + the Codex auth-refresh fix — zero dependencies,
  ready today).
- **Wave 2 (up to 3 concurrent, after wave 1):** Component 1 (ingestion, needs
  10) · Component 4 (repair loop + `case_drafting.py`, needs 5 + 3) ·
  Component 8 (re-investigation, needs 5 + 3 + 10).
- **Wave 3 (up to 3 concurrent, after wave 2):** Component 2 (task
  identification + `outcome_judge.py`, needs 1) · Component 6 (economics,
  needs 3 + 4) · Component 9 (meta-tracing wiring, needs 1, lowest priority —
  slot in whenever a worker is free).
- **Wave 4:** Component 7 (reporting, needs 6) · Component 11 (review
  console, needs 10 + component 4's safety review, both done by wave 2).

Treat this as a strong default, not a guarantee every dependency is fully
captured — sanity-check each wave's job specs against what the previous
wave actually shipped before queueing it.

## Critical files

- `predictor/features.py`, `predictor/contracts.py` — keep, shared foundation.
- `promotion_engine/classifier.py`, `workflow.py`, `reporting.py`,
  `family_jobs.py` — keep, consolidation/extension targets.
- `scripts/evaluate_airline_flight_change_repair.py`,
  `scripts/run_airline_flight_change_repair_controller.sh` — extraction source
  for `sosog/repair/`, then reduced to thin CLI entry points.
- `infra/aws/run_codex_agent.sh` — execution substrate for every Type A job;
  its auth-status preflight is shared infrastructure, not vertical repair
  logic.
- `research_ops/persistence.py`, `infra/aws/sql/001_sosog_research.sql` —
  reference/superseded by `sosog/persistence/store.py` and `002_sosog_v1.sql`.

## Decisions log (all open questions resolved)

1. **Package layout:** confirmed as designed — `sosog/` new package, imports
   from `predictor`/`promotion_engine`, never the reverse.
2. **Success-oracle for client data:** resolved — LLM-judged outcome labeling
   (component 2's `outcome_judge.py`), ranked below `client_label`/
   `programmatic_verifier` in trust.
3. **Spot-check calibration sample rate:** 8% of `llm_judged` episodes,
   tightened for any task type trending toward `FULL_CRYSTALLIZE`.
4. **What `DROP` means on a client report:** its own bucket,
   `INSUFFICIENT_EVIDENCE` — never silently folded into `FULLY_AGENTIC` or
   `FULLY_MANUAL`.
5. **Locked adversarial test case authorship:** resolved — AI drafts from the
   client's policy docs (`sosog/repair/case_drafting.py`), human
   reviews/approves before anything is locked.
6. **New database name + env-var convention:** `sosog_v1`, via a new
   `SOSOG_DB_NAME` env var alongside the existing `DB_HOST`/`DB_PORT`/
   `DB_USER`/`DB_PASSWORD` (shared instance, separate database from the
   research-only `sosog_research` schema).

## Before handing this to Codex to execute

This document is an architecture, not a bounded coding-job spec — handing the
whole thing to one Codex session as-is reproduces exactly the unbounded-task
problem the manifest system (`allowed_changed_paths`, `max_changed_files`)
exists to prevent. Slice the build order above into discrete bounded jobs, one
manifest/prompt per component (or sub-piece of one), the same way
`promotion_engine/family_jobs.py` already scopes the airline repair job to
exactly three allowed paths. Wave 1's three jobs are ready to write as-is —
every decision that shapes their code is resolved above.

## First real-world validation (before/alongside wave 3-4)

Don't validate the finished pipeline against synthetic data first — testing
against data generated from your own assumptions about what real traces look
like mostly confirms those assumptions, it doesn't check them (same
self-grading problem as the safety-review gate, applied to test data).
Synthetic generation stays valuable *after* a real baseline exists, for
adversarial stress-testing — exactly how it's already used for the airline
locked test set — not as the first check.

1. **Dogfood first, free and immediate — completed 2026-08-24:** point the pipeline at SOSOG's own
   Codex worker traces (component 9) as soon as components 1/2/3 exist. Real,
   non-benchmark, already being generated, and directly checkable — you know
   this domain well enough to tell if the clustering/classification output is
   sane. The initial 38-episode result is recorded in component 9 above and
   passed database/redaction/artifact verification.
2. **Then a real external non-benchmark source:** real coding-agent session
   datasets exist and are worth pulling in — SWE-chat (via Entire.io, 2.7M
   events across 200+ real GitHub repos, with human-vs-agent line attribution
   on the resulting commits — genuinely useful as a real outcome-judge
   ground-truth signal, not just realistic input) and SpecStory (real
   developer coding-agent session exports, Sept 2024-Apr 2026). No comparable
   open dataset was found for customer-support-style agent traces (closer to
   the original retail/airline pitch) — that gap likely gets filled by an
   actual design partner later, not solved here.
