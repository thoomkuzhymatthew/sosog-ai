-- Operational history for repair and economics, plus guarded human decisions.
-- Run while connected to the sosog_v1 database after migrations 002 and 003.
CREATE SCHEMA IF NOT EXISTS sosog_v1;

CREATE TABLE IF NOT EXISTS sosog_v1.artifacts (
    artifact_id text PRIMARY KEY,
    engagement_id text NOT NULL DEFAULT 'default' CHECK (btrim(engagement_id) <> ''),
    kind text NOT NULL CHECK (btrim(kind) <> ''),
    uri text NOT NULL CHECK (btrim(uri) <> ''),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-fA-F]{64}$'),
    size_bytes bigint CHECK (size_bytes IS NULL OR size_bytes >= 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (uri, sha256)
);

CREATE TABLE IF NOT EXISTS sosog_v1.proposals (
    proposal_id text PRIMARY KEY,
    engagement_id text NOT NULL DEFAULT 'default' CHECK (btrim(engagement_id) <> ''),
    task_type_id text NOT NULL REFERENCES sosog_v1.task_types(task_type_id),
    classification_id text REFERENCES sosog_v1.classifications(classification_id),
    version integer NOT NULL CHECK (version >= 1),
    status text NOT NULL CHECK (status IN (
        'DRAFT', 'EVALUATING', 'REPAIR_REQUIRED',
        'PENDING_HUMAN_SAFETY_REVIEW', 'APPROVED', 'REJECTED', 'BLOCKED'
    )),
    artifact_id text NOT NULL REFERENCES sosog_v1.artifacts(artifact_id),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (engagement_id, task_type_id, version)
);

CREATE TABLE IF NOT EXISTS sosog_v1.repair_runs (
    repair_run_id text PRIMARY KEY,
    engagement_id text NOT NULL DEFAULT 'default' CHECK (btrim(engagement_id) <> ''),
    proposal_id text NOT NULL REFERENCES sosog_v1.proposals(proposal_id),
    attempt_number integer NOT NULL CHECK (attempt_number >= 0),
    status text NOT NULL CHECK (status IN (
        'ACCEPTED', 'REJECTED', 'EVALUATOR_FAILURE', 'WORKER_FAILURE',
        'DUPLICATE_CANDIDATE', 'OSCILLATING_CANDIDATE', 'COST_LIMIT',
        'TIME_LIMIT'
    )),
    stop_reason text CHECK (stop_reason IS NULL OR stop_reason IN (
        'STAGNATED', 'DUPLICATE_CANDIDATE', 'OSCILLATING',
        'REGRESSED_SAFETY', 'ATTEMPT_LIMIT', 'COST_LIMIT', 'TIME_LIMIT',
        'EVALUATOR_BLOCKED', 'WORKER_BLOCKED', 'NO_SAFE_IMPROVEMENT',
        'PENDING_HUMAN_SAFETY_REVIEW'
    )),
    candidate_fingerprint text CHECK (
        candidate_fingerprint IS NULL OR candidate_fingerprint ~ '^[0-9a-fA-F]{64}$'
    ),
    feedback_fingerprint text CHECK (
        feedback_fingerprint IS NULL OR feedback_fingerprint ~ '^[0-9a-fA-F]{64}$'
    ),
    score jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(score) = 'object'),
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence) = 'object'),
    cost_usd numeric(14, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at),
    UNIQUE (proposal_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS sosog_v1.budget_events (
    budget_event_id text PRIMARY KEY,
    engagement_id text NOT NULL DEFAULT 'default' CHECK (btrim(engagement_id) <> ''),
    job_id text,
    episode_id text REFERENCES sosog_v1.episodes(episode_id) ON DELETE SET NULL,
    repair_run_id text REFERENCES sosog_v1.repair_runs(repair_run_id) ON DELETE SET NULL,
    event_kind text NOT NULL CHECK (btrim(event_kind) <> ''),
    amount_usd numeric(14, 6) NOT NULL CHECK (amount_usd >= 0),
    input_tokens bigint CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens bigint CHECK (output_tokens IS NULL OR output_tokens >= 0),
    model text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sosog_v1.review_items (
    review_item_id text PRIMARY KEY,
    engagement_id text NOT NULL DEFAULT 'default' CHECK (btrim(engagement_id) <> ''),
    review_type text NOT NULL CHECK (btrim(review_type) <> ''),
    subject_type text NOT NULL CHECK (btrim(subject_type) <> ''),
    subject_id text NOT NULL CHECK (btrim(subject_id) <> ''),
    status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    context jsonb NOT NULL CHECK (jsonb_typeof(context) = 'object'),
    decision jsonb CHECK (decision IS NULL OR jsonb_typeof(decision) = 'object'),
    reviewer text,
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    CHECK (
        (status = 'PENDING' AND decision IS NULL AND reviewer IS NULL AND decided_at IS NULL)
        OR (status IN ('APPROVED', 'REJECTED') AND decision IS NOT NULL
            AND reviewer IS NOT NULL AND decided_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS artifacts_engagement_created_idx
    ON sosog_v1.artifacts (engagement_id, created_at, artifact_id);
CREATE INDEX IF NOT EXISTS artifacts_sha256_idx ON sosog_v1.artifacts (sha256);
CREATE INDEX IF NOT EXISTS proposals_task_type_created_idx
    ON sosog_v1.proposals (task_type_id, created_at, proposal_id);
CREATE INDEX IF NOT EXISTS proposals_engagement_status_idx
    ON sosog_v1.proposals (engagement_id, status, created_at);
CREATE INDEX IF NOT EXISTS repair_runs_proposal_attempt_idx
    ON sosog_v1.repair_runs (proposal_id, attempt_number);
CREATE INDEX IF NOT EXISTS repair_runs_engagement_created_idx
    ON sosog_v1.repair_runs (engagement_id, created_at, repair_run_id);
CREATE INDEX IF NOT EXISTS budget_events_engagement_created_idx
    ON sosog_v1.budget_events (engagement_id, created_at, budget_event_id);
CREATE INDEX IF NOT EXISTS budget_events_episode_created_idx
    ON sosog_v1.budget_events (episode_id, created_at);
CREATE INDEX IF NOT EXISTS budget_events_repair_created_idx
    ON sosog_v1.budget_events (repair_run_id, created_at);
CREATE INDEX IF NOT EXISTS review_items_engagement_status_created_idx
    ON sosog_v1.review_items (engagement_id, status, created_at, review_item_id);
CREATE INDEX IF NOT EXISTS review_items_subject_idx
    ON sosog_v1.review_items (subject_type, subject_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS review_items_one_pending_subject_idx
    ON sosog_v1.review_items (
        engagement_id, review_type, subject_type, subject_id
    ) WHERE status = 'PENDING';
