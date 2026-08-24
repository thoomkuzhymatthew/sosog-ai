You are an isolated SOSOG coding worker building product infrastructure, not
a client-facing automation. This job is part of the SOSOG V1 rebuild
described in `docs/V1_ARCHITECTURE_PLAN.md` (component 2) — read that file's
"## 2. Business-task identification (PARTIALLY NEW)" section before starting.
Also read `sosog/ingestion/schema.py` (built by a prior job, already merged
into this base commit) for the exact `NormalizedEpisode` shape you're
consuming — do not assume field names from the architecture doc's
description; the merged implementation is authoritative. Also read
`sosog/persistence/store.py` for the persistence methods you'll write
through, and `crystallized/m5_5_nl_boundary.py` (lines around the
`boto3.client("bedrock-runtime", ...)` / `invoke_model` calls) for this
codebase's existing convention for calling AWS Bedrock — follow that same
client-setup style for the embedding calls below, even though the request/
response body shape differs for an embedding model vs. a completion model.

Your current directory is a detached SOSOG Git worktree.

Fully automated, closed-loop — no blocking human step in this pipeline. The
safety-critical gate in this system belongs later, before any generated
automation goes live; a wrong cluster here only produces a slightly
inaccurate report line item.

## Task

1. **`sosog/task_identification/embed.py`** — one embedding call per
   episode, over the episode's initial request / a short trace summary
   (derive a reasonable summary string from `NormalizedEpisode.calls`).
   Use AWS Bedrock (Titan or Cohere embeddings — pick one, document the
   choice and the exact request/response shape you used in your final
   report, since the architecture doc doesn't pin a specific model ID).
   **This must be injectable/mockable for testing** — accept a Bedrock
   client as a parameter (or via a thin wrapper class) rather than
   constructing one internally with no way to substitute a fake, matching
   how `sosog/persistence/store.py` accepts an injected connection. No live
   AWS call is possible in this sandbox (no network access) — all tests
   must use a fake client returning canned embedding vectors.

2. **`sosog/task_identification/cluster.py`** — two-stage clustering:
   - Stage 1 (free, deterministic): partition episodes by write-call
     skeleton + read-tool multiset, reusing `predictor/features.py:calls_for`/
     `skeleton` **unchanged** — do not modify that file, only import from it.
   - Stage 2: within each skeleton bucket, cluster the embedding vectors
     (from `embed.py`) using **HDBSCAN**, not k-means and not a fixed
     distance-threshold rule. Add `hdbscan` as a new dependency (import
     `hdbscan` directly — if it's not installed in this sandbox's Python
     environment, note that clearly in your report rather than silently
     falling back to a different algorithm; do not substitute k-means or
     agglomerative clustering as a workaround without saying so explicitly).
     Any resulting cluster below a minimum size (default 2 episodes,
     configurable) — or any episode HDBSCAN labels as noise/no-cluster —
     should not become a `task_types` row on its own; treat it as
     insufficient evidence rather than fabricating a task type from a
     one-off trace.
   - Output: for each accepted cluster, a `task_type_id`, its member
     episode IDs, and a representative sample (a small number of example
     episodes, not the whole cluster) to hand to the next step.

3. **`sosog/task_identification/label.py`** — one Bedrock Haiku completion
   call **per accepted cluster** (not per episode — this must be
   O(number of clusters), not O(number of episodes)) that summarizes the
   cluster's representative example episodes into a short task name and a
   one-paragraph description. Same injectable-client requirement as
   `embed.py` — no live call possible in tests.

4. **`sosog/task_identification/review.py`** — an async correction
   mechanism, not a gate: a human-editable override file (JSON, same
   convention as `predictor/labels.py:apply_override` — read that function
   for the pattern, but do not import from or modify `predictor/labels.py`)
   that can merge two cluster IDs, split one, or rename one. Applying an
   override never blocks or is required before clusters are usable — it's a
   correction path a human can invoke after the fact.

5. Persist accepted clusters as `task_types` rows via
   `sosog/persistence/store.py`'s `record_task_type` method (source =
   `"AUTO_CLUSTERED"`, or `"HUMAN_CONFIRMED"` if a review override touched
   it).

## Constraints

- **No live network or database access is available to you in this
  sandbox.** Every test must use a fake Bedrock client and a fake/mock
  persistence store — no real AWS or Postgres calls.
- Do not modify `predictor/features.py`, `predictor/labels.py`,
  `sosog/ingestion/schema.py`, or `sosog/persistence/store.py`.
- `outcome_judge.py` (per-episode success/failure judging using a cluster's
  rubric) is explicitly **out of scope for this job** — a sibling job may be
  building it concurrently against the same base commit, with a decoupled
  interface that takes a rubric string as a plain argument rather than
  importing anything from this job's modules. Do not build it here.

You may change exactly these paths:
- `sosog/task_identification/__init__.py`
- `sosog/task_identification/embed.py`
- `sosog/task_identification/cluster.py`
- `sosog/task_identification/label.py`
- `sosog/task_identification/review.py`
- `sosog/task_identification/tests/__init__.py`
- `sosog/task_identification/tests/test_cluster.py`
- `sosog/task_identification/tests/test_embed.py`

Note: a sibling job running concurrently against this same base commit may
also independently create `sosog/task_identification/__init__.py`. This is
expected — when a human applies both diffs afterward, keep either copy.

The host will reject any other changed path, more than 8 changed files, or a
diff above 1200000 bytes. Do not commit, merge, push, deploy, access
credentials, or enable network access.

Add focused tests covering: skeleton partitioning correctness, HDBSCAN
clustering behavior on fake embedding vectors designed to produce at least
two clear clusters and at least one noise point, the minimum-cluster-size
rejection, a fake-client label-generation call, and an override
merge/split/rename via `review.py`. Run the tests. In your final report:
list changed files, test commands run and their results, which Bedrock
embedding model you chose and its exact request/response shape, whether
`hdbscan` was actually importable in this environment, and any risks a human
reviewer should check. Your work is a proposal and cannot approve itself for
merging.
