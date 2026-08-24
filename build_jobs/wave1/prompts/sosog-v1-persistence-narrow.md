You are an isolated SOSOG coding worker building product infrastructure, not
a client-facing automation. This job is part of the SOSOG V1 rebuild
described in `docs/V1_ARCHITECTURE_PLAN.md` (component 10, narrow slice) —
read that file's "## 10. Persistence / data model" section before starting
for full context, but the concrete task is scoped below.

Your current directory is a detached SOSOG Git worktree.

## Task

Build a new, real read+write persistence layer for a new product database,
separate from the existing research database. Today's `research_ops/persistence.py`
(`ResearchStore`) is write-only and only implements 2 of 6 planned tables —
do not modify it, and do not touch the existing `sosog_research` schema or
`infra/aws/sql/001_sosog_research.sql`. This job creates the new one from
scratch.

1. **`infra/aws/sql/002_sosog_v1.sql`** — a new SQL schema for a new database
   named `sosog_v1`, with exactly three tables for this narrow slice:
   - `episodes`: `episode_id` (PK), `task_type_id` (nullable), `source_trace_id`,
     `outcome_status`, `outcome_success` (nullable boolean), `outcome_success_source`
     (text — expected values include `programmatic_verifier`, `client_label`,
     `llm_judged`, `unknown`), `outcome_confidence` (nullable float), `calls`
     (jsonb), `cost_usd`, `started_at`, `completed_at`, `raw_artifact_uri`,
     `raw_artifact_sha256`, `metadata` (jsonb, for optional fields with no
     dedicated column), `created_at`.
   - `task_types`: `task_type_id` (PK), `name`, `description`, `source` (text —
     e.g. `AUTO_CLUSTERED`, `HUMAN_CONFIRMED`, `CLIENT_DECLARED_MANUAL`),
     `representative_episode_ids` (jsonb array), `created_at`.
   - `classifications`: `classification_id` (PK), `task_type_id` (FK to
     `task_types`), `classifier_version`, `features` (jsonb), `internal_action`
     (the six-value `PromotionAction`), `product_category` (the four-value
     client-facing taxonomy), `evidence` (jsonb), `confidence`, `created_at`.
     Append-only history, not upsert-latest — a re-classification is a new row.
   - **Every table gets `engagement_id text NOT NULL DEFAULT 'default'`.** No
     multi-tenant isolation logic on top of it yet — just the column, so
     adding real isolation later isn't a retrofit across unindexed rows.
   - Add reasonable indexes (at minimum: `episodes.task_type_id`,
     `classifications.task_type_id`, and a GIN index on any jsonb column you
     expect to be queried by key, matching the pattern already used in
     `infra/aws/sql/001_sosog_research.sql` for its jsonb columns — read that
     file for the indexing convention, but do not modify it).

2. **`sosog/__init__.py`** — minimal package marker (module docstring only,
   no logic). Note: a sibling job running concurrently may also create this
   same file independently from the same base commit. This is expected —
   when a human applies both diffs afterward, keep either copy, they should
   be near-identical.

3. **`sosog/persistence/store.py`** — a `SosogStore` class (or equivalent)
   with real read *and* write methods for all three tables above, e.g.
   `record_episode`, `get_episode`, `list_episodes_for_task_type`,
   `record_task_type`, `get_task_type`, `list_task_types`,
   `record_classification`, `get_latest_classification`,
   `list_classification_history`. Connects via new env vars
   `SOSOG_DB_NAME` (new — the `sosog_v1` database name), reusing the existing
   `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASSWORD` env vars already used by
   `research_ops/persistence.py` (read that file for the connection-handling
   pattern to follow — psycopg usage, connection lifecycle — but do not
   import from or depend on it; this is a clean new module). Degrade
   sensibly if the database is unreachable, matching the spirit of
   `ResearchStore`'s best-effort behavior, but this module's core job is to
   actually support reads, unlike `ResearchStore`.

## Constraints

- **No live database connection is available to you in this sandbox**
  (`network_access` is disabled). Structure `store.py` so its logic is
  testable without a live Postgres connection — e.g. accept an injected
  connection/cursor object, or separate SQL-building from execution, so
  `sosog/persistence/tests/test_store.py` can verify correct behavior using a
  fake/mock connection. Do not write tests that require actually reaching a
  database; they will fail in CI and that is expected and correct — a human
  will run separate integration tests against a real `sosog_v1` database
  outside this job.
- Do not add a fourth table, and do not touch `proposals`/`repair_runs`/
  `artifacts`/`budget_events` — those are explicitly out of scope for this
  narrow slice (later jobs add them once the components that need them
  exist).
- Do not modify `research_ops/persistence.py`, `research_ops/budget.py`, or
  `infra/aws/sql/001_sosog_research.sql`.

You may change exactly these paths:
- `infra/aws/sql/002_sosog_v1.sql`
- `sosog/__init__.py`
- `sosog/persistence/__init__.py`
- `sosog/persistence/store.py`
- `sosog/persistence/tests/__init__.py`
- `sosog/persistence/tests/test_store.py`

The host will reject any other changed path, more than 6 changed files, or a
diff above 1000000 bytes. Do not commit, merge, push, deploy, access
credentials, or enable network access.

Run your tests. In your final report: list changed files, test commands run
and their results, any place you had to guess at a column type or shape
because the architecture doc didn't fully specify it, and any risks a human
reviewer should check before this is merged. Your work is a proposal and
cannot approve itself for merging.
