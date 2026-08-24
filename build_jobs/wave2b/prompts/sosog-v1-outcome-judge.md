You are an isolated SOSOG coding worker building product infrastructure, not
a client-facing automation. This job is part of the SOSOG V1 rebuild
described in `docs/V1_ARCHITECTURE_PLAN.md` (component 2's outcome-judging
piece) — read that file's "## 2. Business-task identification (PARTIALLY
NEW)" section, specifically the `outcome_judge.py` bullet, before starting.
Also read `sosog/ingestion/schema.py` (built by a prior job, already merged
into this base commit) for the exact `NormalizedEpisode` shape, and
`crystallized/m5_5_nl_boundary.py` for this codebase's existing convention
for calling AWS Bedrock (`boto3.client("bedrock-runtime", ...)` /
`invoke_model`) — follow that same client-setup style.

Your current directory is a detached SOSOG Git worktree.

## Background

This is the answer to a real gap: most `NormalizedEpisode` records from a
real client will have `outcome.success_source == "unknown"` — real client
data usually has no ground-truth "did this succeed" label, unlike benchmark
data. This module fills that gap with an LLM judge, ranked below
`programmatic_verifier`/`client_label` in trust (never overrides real
evidence, only fills genuine gaps).

**A sibling job may be building `sosog/task_identification/cluster.py` and
`label.py` concurrently against this same base commit — do not depend on
them.** Design this module's interface to take a plain rubric string as an
argument, not an import from those modules; whatever eventually calls this
function (a later, separate piece of wiring) is responsible for sourcing
that rubric from a cluster's generated description.

## Task

**`sosog/task_identification/outcome_judge.py`** — a function
`judge_outcome(episode: NormalizedEpisode, task_rubric: str, client) -> JudgedOutcome`
(name the return type/dataclass as you see fit) that:

- Only judges episodes where `episode.outcome.success_source == "unknown"`.
  For any other `success_source`, return the episode's existing outcome
  unchanged — this function fills gaps, it never overrides
  `programmatic_verifier` or `client_label` evidence.
- Makes one Bedrock Haiku completion call (injectable client, same pattern
  as required elsewhere in this codebase — no live AWS call is possible in
  this sandbox; accept the client as a parameter so tests can supply a
  fake). The prompt to the model should include: the task rubric (name +
  description of what this task type is supposed to accomplish), and the
  episode's calls/outcome-relevant detail (not the full raw trace
  necessarily — use judgment on what's needed for the model to assess
  success, but don't omit anything that would make the judgment
  unreliable).
- Parses the model's response into a structured result:
  `{success: bool, confidence: float, rationale: str}`, and sets
  `success_source="llm_judged"` on the returned outcome.
- Handle a malformed/unparseable model response by returning
  `success=None, success_source="unknown"` (i.e., fail safe back to
  "unknown" rather than guessing at a boolean from a bad response) with the
  rationale explaining the parse failure.

Do **not** build the calibration/spot-check sampling mechanism (routing a
fraction of `llm_judged` episodes to a human review queue) in this job — that
depends on `promotion_engine/audit.py`'s ported audit machinery (already
merged into this base commit) and is a separate, later piece of wiring. This
job only needs to produce the judgment; something else later decides which
judgments get sampled for human review.

## Constraints

- **No live network access is available to you in this sandbox.** All tests
  must use a fake Bedrock client.
- Do not modify `sosog/ingestion/schema.py`, `promotion_engine/audit.py`, or
  any file outside the ones listed below.
- Do not build `sosog/task_identification/cluster.py` or `label.py` — those
  are out of scope for this job.

You may change exactly these paths:
- `sosog/task_identification/__init__.py`
- `sosog/task_identification/outcome_judge.py`
- `sosog/task_identification/tests/__init__.py`
- `sosog/task_identification/tests/test_outcome_judge.py`

Note: a sibling job running concurrently against this same base commit may
also independently create `sosog/task_identification/__init__.py` and
`sosog/task_identification/tests/__init__.py`. This is expected — when a
human applies both diffs afterward, keep either copy.

The host will reject any other changed path, more than 4 changed files, or a
diff above 700000 bytes. Do not commit, merge, push, deploy, access
credentials, or enable network access.

Add focused tests covering: an episode with `success_source != "unknown"`
passes through unchanged (judge is never called), a well-formed fake model
response producing a correct `JudgedOutcome` with `success_source=
"llm_judged"`, and a malformed fake model response failing safe to
`success=None`/`success_source="unknown"` rather than guessing. Run the
tests. In your final report: list changed files, test commands run and
their results, the exact prompt template you used for the judge call, and
any risks a human reviewer should check — especially around what happens if
the rubric passed in is empty or missing (since this module doesn't control
where the rubric comes from). Your work is a proposal and cannot approve
itself for merging.
