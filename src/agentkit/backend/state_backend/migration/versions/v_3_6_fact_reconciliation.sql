-- AG3-117 migration v3.6 — Fact-Column-Reconciliation onto FK-62 §62.2.
-- FK-62 §62.2.1-62.2.5 (DDL truth), FK-60 §60 P3 (recompute-disposable rollups).
--
-- This migration brings the five fact_* tables onto the FK-62 §62.2 column set:
-- renames (story_mode->pipeline_mode, started_at->opened_at,
-- completed_at->closed_at, qa_rounds->qa_round_count,
-- adversarial_findings->adversarial_findings_count,
-- are_gate_status->are_gate_passed [str->bool/INTEGER],
-- guard_id->guard_key [PK], llm_role->pool_key [PK],
-- incidents_recorded->new_incident_count, patterns_promoted->patterns_total_count,
-- checks_approved->patterns_with_active_check, stories_completed->story_count_closed,
-- avg_qa_rounds->qa_round_avg), the ~54 new FK-62 columns, and the drops of all
-- non-FK-62 columns (token_input_total, token_output_total, avg_latency_ms,
-- agentkit_version, agentkit_commit, period_end x4, stories_escalated,
-- avg_phase_implementation_ms).
--
-- MECHANIC = DROP + REBUILD (no RENAME COLUMN, no PK ALTER): SQLite cannot alter a
-- composite PK in place (guard_id->guard_key / llm_role->pool_key are PK columns),
-- so a portable (SQLite + Postgres) drop+rebuild is cleaner than ALTER acrobatics.
--
-- NO DATA MIGRATION: the fact_* tables are recompute-disposable rollups
-- (FK-60 §60 P3 "analytics is recomputable from the raw data at any time",
-- :167; the Refresh-Worker recomputes affected slices completely, :366). Existing
-- rollup rows are a derivable projection, NOT a data corpus to preserve — the
-- DROP discards them and the RefreshWorker re-derives them from the events.
--
-- This file is a forward-only, additive migration step (registered as 3.6 in
-- migration_runner._MIGRATIONS); v_3_4_analytics.sql and v_3_5_compaction_epochs.sql
-- stay unchanged. Fresh DBs run 3.4->3.5->3.6 and land directly on the FK-62 schema;
-- already-3.4/3.5 DBs get 3.6 pulled in cleanly. The canonical column/PK truth is
-- mirrored in postgres_schema.sql (Postgres dialect) and the fact-store models /
-- mappers; this file is the SQLite schema-version record of WHAT 3.6 introduced.
--
-- Tenant rule (FK-62 §62.2): project_key is the leading scope key.

DROP TABLE IF EXISTS fact_story;
DROP TABLE IF EXISTS fact_guard_period;
DROP TABLE IF EXISTS fact_pool_period;
DROP TABLE IF EXISTS fact_pipeline_period;
DROP TABLE IF EXISTS fact_corpus_period;

CREATE TABLE IF NOT EXISTS fact_story (
    project_key                 TEXT NOT NULL,
    story_id                    TEXT NOT NULL,
    story_type                  TEXT NOT NULL,
    story_size                  TEXT NOT NULL,
    pipeline_mode               TEXT,
    opened_at                   TEXT NOT NULL,
    closed_at                   TEXT,
    processing_time_ms          INTEGER,
    compaction_count            INTEGER NOT NULL DEFAULT 0,
    qa_round_count              INTEGER NOT NULL DEFAULT 0,
    feedback_converged          INTEGER,
    blocked_ac_count            INTEGER NOT NULL DEFAULT 0,
    blocked_ac_detail_json      TEXT,
    llm_call_count              INTEGER NOT NULL DEFAULT 0,
    adversarial_findings_count  INTEGER NOT NULL DEFAULT 0,
    adversarial_tests_created   INTEGER NOT NULL DEFAULT 0,
    adversarial_hit_rate        REAL,
    findings_fully_resolved     INTEGER NOT NULL DEFAULT 0,
    findings_partially_resolved INTEGER NOT NULL DEFAULT 0,
    findings_not_resolved       INTEGER NOT NULL DEFAULT 0,
    final_status                TEXT,
    are_gate_passed             INTEGER,
    are_total_requirements      INTEGER,
    are_covered_requirements    INTEGER,
    files_changed               INTEGER NOT NULL DEFAULT 0,
    increment_count             INTEGER NOT NULL DEFAULT 0,
    phase_setup_ms              INTEGER,
    phase_exploration_ms        INTEGER,
    phase_implementation_ms     INTEGER,
    phase_verify_ms             INTEGER,
    phase_closure_ms            INTEGER,
    computed_at                 TEXT NOT NULL,
    PRIMARY KEY (project_key, story_id)
);

CREATE INDEX IF NOT EXISTS idx_fact_story_project_closed
    ON fact_story (project_key, closed_at);

CREATE TABLE IF NOT EXISTS fact_guard_period (
    project_key              TEXT NOT NULL,
    guard_key                TEXT NOT NULL,
    period_start             TEXT NOT NULL,
    period_grain             TEXT NOT NULL DEFAULT 'week',
    invocation_count         INTEGER NOT NULL DEFAULT 0,
    violation_count          INTEGER NOT NULL DEFAULT 0,
    violation_rate           REAL,
    violation_stage_escape   INTEGER NOT NULL DEFAULT 0,
    violation_stage_schema   INTEGER NOT NULL DEFAULT 0,
    violation_stage_template INTEGER NOT NULL DEFAULT 0,
    escape_detection_count   INTEGER NOT NULL DEFAULT 0,
    computed_at              TEXT NOT NULL,
    PRIMARY KEY (project_key, guard_key, period_start)
);

CREATE INDEX IF NOT EXISTS idx_fact_guard_period_project_start
    ON fact_guard_period (project_key, period_start);

CREATE TABLE IF NOT EXISTS fact_pool_period (
    project_key                  TEXT NOT NULL,
    pool_key                     TEXT NOT NULL,
    period_start                 TEXT NOT NULL,
    period_grain                 TEXT NOT NULL DEFAULT 'week',
    call_count                   INTEGER NOT NULL DEFAULT 0,
    response_time_p50_ms         INTEGER,
    verdict_adopted_count        INTEGER NOT NULL DEFAULT 0,
    verdict_total_count          INTEGER NOT NULL DEFAULT 0,
    finding_true_positive_count  INTEGER NOT NULL DEFAULT 0,
    finding_false_positive_count INTEGER NOT NULL DEFAULT 0,
    quorum_triggered_count       INTEGER NOT NULL DEFAULT 0,
    template_finding_rate_json   TEXT,
    computed_at                  TEXT NOT NULL,
    PRIMARY KEY (project_key, pool_key, period_start)
);

CREATE INDEX IF NOT EXISTS idx_fact_pool_period_project_start
    ON fact_pool_period (project_key, period_start);

CREATE TABLE IF NOT EXISTS fact_pipeline_period (
    project_key                         TEXT NOT NULL,
    period_start                        TEXT NOT NULL,
    period_grain                        TEXT NOT NULL DEFAULT 'week',
    story_count                         INTEGER NOT NULL DEFAULT 0,
    story_count_closed                  INTEGER NOT NULL DEFAULT 0,
    execution_count                     INTEGER NOT NULL DEFAULT 0,
    exploration_count                   INTEGER NOT NULL DEFAULT 0,
    stage_miss_count                    INTEGER NOT NULL DEFAULT 0,
    stage_miss_detail_json              TEXT,
    impact_violation_count              INTEGER NOT NULL DEFAULT 0,
    impact_check_count                  INTEGER NOT NULL DEFAULT 0,
    integrity_gate_block_count          INTEGER NOT NULL DEFAULT 0,
    integrity_gate_total_count          INTEGER NOT NULL DEFAULT 0,
    doc_fidelity_conflict_by_level_json TEXT,
    first_pass_count                    INTEGER NOT NULL DEFAULT 0,
    finding_survival_count              INTEGER NOT NULL DEFAULT 0,
    finding_total_count                 INTEGER NOT NULL DEFAULT 0,
    effective_check_ids_json            TEXT,
    vectordb_total_hits                 INTEGER NOT NULL DEFAULT 0,
    vectordb_above_threshold            INTEGER NOT NULL DEFAULT 0,
    vectordb_classified_conflict        INTEGER NOT NULL DEFAULT 0,
    vectordb_duplicate_detected         INTEGER NOT NULL DEFAULT 0,
    processing_time_avg_ms              INTEGER,
    processing_time_variance_ms2        REAL,
    qa_round_avg                        REAL,
    computed_at                         TEXT NOT NULL,
    PRIMARY KEY (project_key, period_start)
);

CREATE TABLE IF NOT EXISTS fact_corpus_period (
    project_key                TEXT NOT NULL,
    period_start               TEXT NOT NULL,
    period_grain               TEXT NOT NULL DEFAULT 'month',
    new_incident_count         INTEGER NOT NULL DEFAULT 0,
    patterns_total_count       INTEGER NOT NULL DEFAULT 0,
    patterns_with_active_check INTEGER NOT NULL DEFAULT 0,
    computed_at                TEXT NOT NULL,
    PRIMARY KEY (project_key, period_start)
);
