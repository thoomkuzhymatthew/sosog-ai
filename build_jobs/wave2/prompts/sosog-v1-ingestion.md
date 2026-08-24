You are an isolated SOSOG coding worker building product infrastructure, not
a client-facing automation. This job is part of the SOSOG V1 rebuild
described in `docs/V1_ARCHITECTURE_PLAN.md` (component 1) — read that file's
"## 1. Trace ingestion & normalization (NEW)" section before starting for
full context, but the concrete task is scoped below. Also read
`sosog/persistence/store.py` (built by a prior job, already merged into this
base commit) in full — this job's pipeline writes through it.

Your current directory is a detached SOSOG Git worktree.

## Task

Build the boundary that turns an arbitrary client trace export into the
normalized episode records the rest of the system consumes. Nothing today
accepts real client data — every existing consumer assumes benchmark-shaped
rows with a pre-existing `task_id` and a `passed`/`reward` field.

1. **`sosog/ingestion/schema.py`** — a versioned `NormalizedEpisode` record
   (dataclass or similar) with fields: `episode_id`, `task_type_id`
   (nullable — nothing assigns this yet, that's a later job's work),
   `source_trace_id`, `started_at`, `completed_at`, `calls` (a list of
   `{name, arguments, is_write: bool, result}` records — read
   `predictor/features.py`'s `calls_for`/`skeleton` functions to match the
   shape they already expect, since this schema needs to be compatible with
   that existing, unmodified module), `outcome` (a nested structure:
   `status`, `success: bool | None`, `success_source: str`, `confidence:
   float | None`), `cost` (`usd`, `tokens_in`, `tokens_out`, `model`),
   `annotations` (free-form dict), `raw_ref` (pointer to the immutable raw
   artifact this episode was derived from).

   **Critical constraint on `success_source` and `success`:** never guess.
   If the raw export gives you an explicit, trustworthy success signal, set
   `success_source` to `"programmatic_verifier"` (a deterministic check the
   client's own system already performed) or `"client_label"` (a human
   annotation the client provided) as appropriate, and set `success`
   accordingly. If no such signal exists in the raw data, set
   `success_source="unknown"` and `success=None` — **do not** default a
   missing/ambiguous signal to `success=False`. (This is the opposite of
   what `predictor/features.py:run_passed()` does for benchmark data — that
   function is correct for benchmarks, which always have a reward field, and
   you must not modify it. This ingestion path is for data that usually has
   no such field at all, so defaulting to failure would silently corrupt
   every downstream pass-rate calculation.) A later job assigns
   `success_source="llm_judged"` after clustering exists to provide a
   rubric — that is explicitly out of scope here; this job only ever
   produces `programmatic_verifier`, `client_label`, or `unknown`.

2. **`sosog/ingestion/adapters/generic_mapped.py`** — one config-driven
   adapter: `normalize(raw_record: dict, mapping: dict) -> NormalizedEpisode`.
   The `mapping` describes which raw JSON/CSV fields correspond to which
   `NormalizedEpisode` fields (e.g. `{"calls_path": "actions", "call_name_key":
   "tool", ...}` — design a mapping schema that's flexible enough to handle
   varying raw export shapes without writing a new Python adapter per
   client). Follow the config-file pattern already used by
   `config/airline_write_tools.json` (read it for the style/format
   convention) rather than inventing an unrelated config format. Do not
   write bespoke adapters for specific hypothetical export formats — only
   this one generic, configurable adapter.

3. **`sosog/ingestion/redaction.py`** — strips or tokenizes sensitive fields
   (customer names, emails, payment details) out of call arguments/results
   **before** anything is normalized or persisted. Config-driven per client
   (a list of field paths/patterns to redact, similar style to the mapping
   config above) — provide a sensible default config covering common PII
   field-name patterns (e.g. `email`, `name`, `phone`, `card_number`,
   `ssn`), and let a caller override/extend it per client. Apply this before
   `generic_mapped.py`'s output reaches the pipeline below — redaction is a
   protection at the door, not an optional afterthought.

4. **`sosog/ingestion/pipeline.py`** — orchestrates: raw export file →
   immutable artifact (write it somewhere durable and content-addressed by
   its hash before doing anything else with it — read
   `research_ops/persistence.py`'s `_put_immutable`-style pattern, if
   present, for the convention to follow, but do not import from or modify
   that module) → redaction → adapter → basic validation (reject a record
   missing required fields rather than silently producing a malformed
   episode) → persist each `NormalizedEpisode` via `sosog/persistence/store.py`'s
   `record_episode` method.

5. **`config/generic_ingestion_mapping.example.json`** — a filled-in example
   mapping file demonstrating the config shape from item 2, so a future
   integrator has a concrete template to copy and adapt, not just a schema
   description in a docstring.

## Constraints

- **No live database connection or network access is available to you in
  this sandbox.** `sosog/persistence/store.py` was already built to support
  this — its methods accept an injected connection/cursor, so
  `sosog/ingestion/tests/test_pipeline.py` should use a fake/mock store the
  same way `sosog/persistence/tests/test_store.py` does (read that file for
  the pattern). Do not write tests requiring a real database or network
  call.
- Manual (no-agent) tasks are explicitly out of scope for this job — this
  pipeline only ever processes traces that exist; a separate client-declared
  manual-task registry is a different, later piece of work.
- Assigning `task_type_id` is out of scope — that's clustering (a later
  job); every episode this pipeline produces should leave it `None`.
- Do not modify `predictor/features.py`, `predictor/contracts.py`,
  `sosog/persistence/store.py`, or `research_ops/persistence.py`.

You may change exactly these paths:
- `sosog/ingestion/__init__.py`
- `sosog/ingestion/schema.py`
- `sosog/ingestion/adapters/__init__.py`
- `sosog/ingestion/adapters/generic_mapped.py`
- `sosog/ingestion/pipeline.py`
- `sosog/ingestion/redaction.py`
- `sosog/ingestion/tests/__init__.py`
- `sosog/ingestion/tests/test_pipeline.py`
- `config/generic_ingestion_mapping.example.json`

The host will reject any other changed path, more than 9 changed files, or a
diff above 1200000 bytes. Do not commit, merge, push, deploy, access
credentials, or enable network access.

Add focused tests covering: a clean end-to-end normalize-and-persist run
against a fake store, a record with an explicit success signal producing the
right `success_source`, a record with no success signal producing
`success_source="unknown"`/`success=None` (never `False`), redaction
actually removing a sensitive field before persistence, and rejection of a
malformed raw record. Run the tests. In your final report: list changed
files, test commands run and their results, the exact mapping-config schema
you designed (since the architecture doc didn't fully specify one), and any
risks a human reviewer should check. Your work is a proposal and cannot
approve itself for merging.
