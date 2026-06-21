-- AG3-038 migration v3.4 — analytics fact tables + sync_state + scratchpad.
-- FK-62 §62.2.1-62.2.7, FK-60 §60.3.4, FK-18 §18.9a.
--
-- This is the AG3-005-style side-by-side migration artifact for the analytics
-- schema layer. Every statement is idempotent (CREATE TABLE / CREATE INDEX IF
-- NOT EXISTS) and re-runnable with no error, no duplicate, NO DROP/RECREATE.
-- The DDL is portable across SQLite and Postgres: it uses no schema prefix
-- (story §2.1.4 / §8 — see postgres_schema.sql for the schema-placement note)
-- and only types/affinities valid on both backends (TEXT/INTEGER/REAL map onto
-- Postgres TEXT/INTEGER/NUMERIC and onto SQLite affinities; timestamps are
-- stored as TEXT/TIMESTAMPTZ by the canonical schema owner and roundtripped by
-- the mapper). The canonical column/PK truth lives in
-- ``postgres_schema.sql`` / ``sqlite_store._ensure_analytics_tables``; this file
-- is the migration-cursor's record of WHAT schema version 3.4 introduced.
--
-- Mandantenregel (FK-62 §62.2): project_key is the leading scope key.

CREATE TABLE IF NOT EXISTS fact_story (
    project_key               TEXT NOT NULL,
    story_id                  TEXT NOT NULL,
    story_type                TEXT NOT NULL,
    story_size                TEXT NOT NULL,
    story_mode                TEXT,
    started_at                TEXT NOT NULL,
    completed_at              TEXT,
    qa_rounds                 INTEGER NOT NULL,
    compaction_count          INTEGER,
    llm_call_count            INTEGER,
    adversarial_findings      INTEGER,
    adversarial_tests_created INTEGER,
    files_changed             INTEGER,
    feedback_converged        INTEGER,
    phase_setup_ms            INTEGER,
    phase_implementation_ms   INTEGER,
    phase_closure_ms          INTEGER,
    are_gate_status           TEXT,
    agentkit_version          TEXT NOT NULL,
    agentkit_commit           TEXT NOT NULL,
    PRIMARY KEY (project_key, story_id)
);

CREATE INDEX IF NOT EXISTS idx_fact_story_project_completed
    ON fact_story (project_key, completed_at);

CREATE TABLE IF NOT EXISTS fact_guard_period (
    project_key      TEXT NOT NULL,
    guard_id         TEXT NOT NULL,
    period_start     TEXT NOT NULL,
    period_end       TEXT NOT NULL,
    invocation_count INTEGER NOT NULL,
    violation_count  INTEGER NOT NULL,
    PRIMARY KEY (project_key, guard_id, period_start)
);

CREATE INDEX IF NOT EXISTS idx_fact_guard_period_project_start
    ON fact_guard_period (project_key, period_start);

CREATE TABLE IF NOT EXISTS fact_pool_period (
    project_key        TEXT NOT NULL,
    llm_role           TEXT NOT NULL,
    period_start       TEXT NOT NULL,
    period_end         TEXT NOT NULL,
    call_count         INTEGER NOT NULL,
    token_input_total  INTEGER NOT NULL,
    token_output_total INTEGER NOT NULL,
    avg_latency_ms     INTEGER,
    PRIMARY KEY (project_key, llm_role, period_start)
);

CREATE INDEX IF NOT EXISTS idx_fact_pool_period_project_start
    ON fact_pool_period (project_key, period_start);

CREATE TABLE IF NOT EXISTS fact_pipeline_period (
    project_key                 TEXT NOT NULL,
    period_start                TEXT NOT NULL,
    period_end                  TEXT NOT NULL,
    stories_completed           INTEGER NOT NULL,
    stories_escalated           INTEGER NOT NULL,
    avg_qa_rounds               REAL,
    avg_phase_implementation_ms INTEGER,
    PRIMARY KEY (project_key, period_start)
);

CREATE TABLE IF NOT EXISTS fact_corpus_period (
    project_key        TEXT NOT NULL,
    period_start       TEXT NOT NULL,
    period_end         TEXT NOT NULL,
    incidents_recorded INTEGER NOT NULL,
    patterns_promoted  INTEGER NOT NULL,
    checks_approved    INTEGER NOT NULL,
    PRIMARY KEY (project_key, period_start)
);

-- FK-62 §62.2.7: project-scoped generic key-value sync cursor. NO global
-- refresh pointer across projects. Known keys: last_event_id, last_synced_at,
-- schema_version.
CREATE TABLE IF NOT EXISTS sync_state (
    project_key TEXT NOT NULL,
    key         TEXT NOT NULL,
    value_int   INTEGER,
    value_text  TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (project_key, key)
);

-- FK-62 §62.2.6 / FK-61 §61.4.3: guard-invocation scratchpad. Weekly key grain
-- supports reset + weekly rollup; invocations/blocks are the rate components the
-- RefreshWorker drains into fact_guard_period.
CREATE TABLE IF NOT EXISTS guard_invocation_counters (
    project_key TEXT NOT NULL,
    story_id    TEXT NOT NULL,
    guard_key   TEXT NOT NULL,
    week_start  TEXT NOT NULL,
    invocations INTEGER NOT NULL DEFAULT 0,
    blocks      INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (project_key, story_id, guard_key, week_start)
);
