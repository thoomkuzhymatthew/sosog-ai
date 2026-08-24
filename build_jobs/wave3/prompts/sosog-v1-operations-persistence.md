You are an isolated SOSOG coding worker expanding the V1 Postgres boundary for
repair, economics, and human review. Read `docs/REPAIR_LOOP_DESIGN.md`,
Component 10 of `docs/V1_ARCHITECTURE_PLAN.md`, all existing `002`/`003`
migrations, and `sosog/persistence/store.py` plus its tests.

Build `infra/aws/sql/004_sosog_v1_operations.sql` as an idempotent migration
adding the missing append-only operational tables:

- `artifacts`: content-addressed URI/SHA, kind, metadata and engagement;
- `proposals`: task type, optional classification, version/status, immutable
  artifact reference, metadata/evidence;
- `repair_runs`: proposal, attempt number, status/stop reason, candidate and
  feedback fingerprints, structured score/evidence, measured cost and times;
- `budget_events`: optional job/episode/repair references, event kind, USD,
  token/model fields and metadata;
- `review_items`: review type, subject type/id, pending/approved/rejected
  status, immutable context, decision, reviewer and timestamps.

Use foreign keys where a real parent exists without making external job IDs
fake FKs. Give every table `engagement_id`. Add useful history/query indexes,
nonnegative/check constraints, JSON type checks, and uniqueness preventing two
repair rows for the same proposal/attempt. Do not mutate or drop existing data.

Expand `SosogStore` with plain append writes and ordered reads for these tables,
including: record/get/list proposals, record/list repair runs, record/list
artifacts, record/list budget events, create/list/get/decide review items. A
review decision must be a guarded update from `PENDING`, and the API must not
offer any deploy/merge operation. Preserve best-effort versus required-DB
semantics and injectable fake connections.

Tests must verify SQL/parameter shapes, JSON serialization, ordering, required
fields, guarded review decisions, and migration invariants by inspecting the
SQL text. No live database or network. Do not commit, merge, push, deploy, or
access credentials. Your result is a proposal requiring independent review.
