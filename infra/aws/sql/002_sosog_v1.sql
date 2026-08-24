-- Run this migration while connected to the sosog_v1 database.
CREATE SCHEMA IF NOT EXISTS sosog_v1;

CREATE TABLE IF NOT EXISTS sosog_v1.task_types (
    task_type_id text PRIMARY KEY,
    engagement_id text NOT NULL DEFAULT 'default',
    name text NOT NULL,
    description text NOT NULL,
    source text NOT NULL,
    representative_episode_ids jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
        jsonb_typeof(representative_episode_ids) = 'array'
    ),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sosog_v1.episodes (
    episode_id text PRIMARY KEY,
    engagement_id text NOT NULL DEFAULT 'default',
    task_type_id text REFERENCES sosog_v1.task_types(task_type_id) ON DELETE SET NULL,
    source_trace_id text NOT NULL,
    outcome_status text NOT NULL,
    outcome_success boolean,
    outcome_success_source text NOT NULL DEFAULT 'unknown',
    outcome_confidence double precision CHECK (
        outcome_confidence IS NULL OR outcome_confidence BETWEEN 0 AND 1
    ),
    calls jsonb NOT NULL DEFAULT '[]'::jsonb,
    cost_usd numeric(14, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
    started_at timestamptz,
    completed_at timestamptz,
    raw_artifact_uri text,
    raw_artifact_sha256 text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sosog_v1.classifications (
    classification_id text PRIMARY KEY,
    engagement_id text NOT NULL DEFAULT 'default',
    task_type_id text NOT NULL REFERENCES sosog_v1.task_types(task_type_id),
    classifier_version text NOT NULL,
    features jsonb NOT NULL DEFAULT '{}'::jsonb,
    internal_action text NOT NULL CHECK (
        internal_action IN (
            'FULL_CRYSTALLIZE', 'RESPONSE_CRYSTALLIZE', 'DECOMPOSE',
            'LIFT', 'RETAIN', 'DROP'
        )
    ),
    product_category text NOT NULL CHECK (
        product_category IN (
            'FULLY_CRYSTALLIZABLE', 'DECOMPOSABLE',
            'FULLY_AGENTIC', 'FULLY_MANUAL'
        )
    ),
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS episodes_task_type_id_idx
    ON sosog_v1.episodes (task_type_id);
CREATE INDEX IF NOT EXISTS episodes_engagement_created_idx
    ON sosog_v1.episodes (engagement_id, created_at);
CREATE INDEX IF NOT EXISTS episodes_metadata_gin_idx
    ON sosog_v1.episodes USING gin (metadata);
CREATE INDEX IF NOT EXISTS task_types_engagement_created_idx
    ON sosog_v1.task_types (engagement_id, created_at);
CREATE INDEX IF NOT EXISTS classifications_task_type_id_idx
    ON sosog_v1.classifications (task_type_id);
CREATE INDEX IF NOT EXISTS classifications_task_type_created_idx
    ON sosog_v1.classifications (task_type_id, created_at DESC);
CREATE INDEX IF NOT EXISTS classifications_features_gin_idx
    ON sosog_v1.classifications USING gin (features);
CREATE INDEX IF NOT EXISTS classifications_evidence_gin_idx
    ON sosog_v1.classifications USING gin (evidence);
