CREATE SCHEMA IF NOT EXISTS sosog_research;

CREATE TABLE IF NOT EXISTS sosog_research.runs (
    run_id text PRIMARY KEY,
    milestone text NOT NULL,
    vertical text NOT NULL,
    status text NOT NULL CHECK (
        status IN ('PLANNED', 'GATING', 'RUNNING', 'PAUSED', 'COMPLETE', 'FAILED', 'DROPPED')
    ),
    subject_model text NOT NULL,
    harness_name text NOT NULL,
    harness_commit text NOT NULL,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    cost_usd numeric(14, 6) NOT NULL DEFAULT 0,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sosog_research.task_runs (
    run_id text NOT NULL REFERENCES sosog_research.runs(run_id) ON DELETE CASCADE,
    task_id text NOT NULL,
    trial integer NOT NULL,
    seed bigint NOT NULL,
    status text NOT NULL,
    passed boolean,
    reward double precision,
    requested_model_route text NOT NULL,
    actual_model_route text,
    fallback_depth integer NOT NULL DEFAULT 0,
    usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    cost_usd numeric(14, 6) NOT NULL DEFAULT 0,
    trace_s3_uri text,
    trace_sha256 text,
    error jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, task_id, trial, seed)
);

CREATE TABLE IF NOT EXISTS sosog_research.task_features (
    snapshot_id text NOT NULL,
    vertical text NOT NULL,
    task_id text NOT NULL,
    feature_version text NOT NULL,
    features jsonb NOT NULL,
    automatic_route text,
    oracle_route text,
    oracle_label_source text,
    costs_by_route jsonb NOT NULL DEFAULT '{}'::jsonb,
    audit jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, vertical, task_id, feature_version)
);

CREATE TABLE IF NOT EXISTS sosog_research.router_predictions (
    snapshot_id text NOT NULL,
    router_version text NOT NULL,
    vertical text NOT NULL,
    task_id text NOT NULL,
    split text NOT NULL CHECK (split IN ('train', 'heldout', 'unassigned')),
    predicted_route text NOT NULL,
    confidence double precision NOT NULL,
    expected_savings numeric(14, 6) NOT NULL,
    regret_usd numeric(14, 6),
    safety_error boolean,
    prediction jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, router_version, vertical, task_id)
);

CREATE TABLE IF NOT EXISTS sosog_research.artifacts (
    run_id text NOT NULL REFERENCES sosog_research.runs(run_id) ON DELETE CASCADE,
    artifact_type text NOT NULL,
    s3_uri text NOT NULL,
    sha256 text NOT NULL,
    size_bytes bigint NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, artifact_type, s3_uri)
);

CREATE TABLE IF NOT EXISTS sosog_research.budget_events (
    event_id bigserial PRIMARY KEY,
    run_id text REFERENCES sosog_research.runs(run_id) ON DELETE SET NULL,
    vertical text NOT NULL,
    event_type text NOT NULL,
    amount_usd numeric(14, 6) NOT NULL,
    cumulative_track_usd numeric(14, 6) NOT NULL,
    cumulative_global_usd numeric(14, 6),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS task_runs_vertical_status_idx
    ON sosog_research.task_runs (run_id, status, task_id);
CREATE INDEX IF NOT EXISTS task_runs_metadata_gin_idx
    ON sosog_research.task_runs USING gin (metadata);
CREATE INDEX IF NOT EXISTS task_features_features_gin_idx
    ON sosog_research.task_features USING gin (features);
CREATE INDEX IF NOT EXISTS budget_events_vertical_created_idx
    ON sosog_research.budget_events (vertical, created_at);
