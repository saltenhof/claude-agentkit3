"""SQLite runtime, artifact, failure-corpus, and analytics DDL bootstrap."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


def _ensure_schema_runtime_tables(conn: sqlite3.Connection) -> None:
    """Create runtime, pipeline, and analytics tables (schema part 2)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS attempts (
            story_id        TEXT     NOT NULL,
            run_id          TEXT     NOT NULL,
            phase           TEXT     NOT NULL,
            attempt         INTEGER  NOT NULL CHECK (attempt >= 1),
            outcome         TEXT     NOT NULL CHECK (outcome IN ('COMPLETED','FAILED','ESCALATED','SKIPPED','YIELDED','BLOCKED')),
            failure_cause   TEXT     NULL CHECK (
                failure_cause IS NULL OR failure_cause IN (
                    'GUARD_REJECTED','STRUCTURAL_CHECK_FAIL','SEMANTIC_REVIEW_FAIL','ADVERSARIAL_FINDING',
                    'POLICY_FAIL','WORKER_BLOCKED','INTEGRITY_FAIL','MERGE_FAIL','PREFLIGHT_FAIL',
                    'MAX_ROUNDS_EXCEEDED','TIMEOUT','GUARD_FAILED','HANDLER_EXCEPTION','PRECONDITION_FAILED',
                    'HANDLER_REPORTED_FAILED','HANDLER_REPORTED_ESCALATED'
                )
            ),
            started_at      TEXT     NOT NULL,
            ended_at        TEXT     NOT NULL,
            detail_json     TEXT     NULL,
            PRIMARY KEY (story_id, run_id, phase, attempt),
            CHECK (ended_at >= started_at),
            CHECK (
                (outcome IN ('FAILED','BLOCKED','ESCALATED') AND failure_cause IS NOT NULL)
                OR (outcome NOT IN ('FAILED','BLOCKED','ESCALATED') AND failure_cause IS NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_attempts_story_run_phase ON attempts (story_id, run_id, phase);
        CREATE INDEX IF NOT EXISTS idx_attempts_outcome ON attempts (outcome);

        CREATE TABLE IF NOT EXISTS flow_executions (
            story_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            run_id TEXT NOT NULL,
            flow_id TEXT NOT NULL,
            level TEXT NOT NULL,
            owner TEXT NOT NULL,
            parent_flow_id TEXT,
            status TEXT NOT NULL,
            current_node_id TEXT,
            attempt_no INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS compaction_epochs (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            epoch INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id)
        );

        CREATE TABLE IF NOT EXISTS node_execution_ledgers (
            story_id TEXT NOT NULL,
            flow_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            project_key TEXT NOT NULL,
            run_id TEXT NOT NULL,
            execution_count INTEGER NOT NULL,
            success_count INTEGER NOT NULL,
            last_outcome TEXT,
            last_attempt_no INTEGER,
            last_executed_at TEXT,
            PRIMARY KEY (story_id, flow_id, node_id)
        );

        CREATE TABLE IF NOT EXISTS execution_events (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            source_component TEXT NOT NULL,
            severity TEXT NOT NULL,
            phase TEXT,
            flow_id TEXT,
            node_id TEXT,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id, event_id)
        );

        CREATE TABLE IF NOT EXISTS story_metrics (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            story_type TEXT NOT NULL,
            story_size TEXT NOT NULL,
            -- mode is the standard/fast axis (WireStoryMode), FK-24 §24.3.298:
            -- closure metrics are tagged with standard/fast so fast runs are
            -- separately aggregable. This is NOT execution_route (AG3-052).
            -- Column stays nullable for legacy rows; new rows always carry a
            -- value (StoryContext.mode defaults to 'standard').
            mode TEXT,
            processing_time_min REAL NOT NULL,
            qa_rounds INTEGER NOT NULL,
            increments INTEGER NOT NULL,
            final_status TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            adversarial_findings INTEGER,
            adversarial_tests_created INTEGER,
            files_changed INTEGER,
            agentkit_version TEXT,
            agentkit_commit TEXT,
            config_version TEXT,
            llm_roles_json TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id)
        );

        CREATE TABLE IF NOT EXISTS override_records (
            override_id TEXT PRIMARY KEY,
            story_id TEXT NOT NULL,
            project_key TEXT NOT NULL,
            run_id TEXT NOT NULL,
            flow_id TEXT NOT NULL,
            target_node_id TEXT,
            override_type TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            consumed_at TEXT,
            -- AG3-108: override->check correlation (FK-69 §69.11 rule 3, §69.15.6
            -- rule 5). NULL for non-check overrides; set when this override
            -- suppresses a specific QA check (outcome = overridden).
            check_id TEXT
        );

        CREATE TABLE IF NOT EXISTS decision_records (
            story_id TEXT NOT NULL,
            decision_kind TEXT NOT NULL,
            attempt_nr INTEGER NOT NULL,
            status TEXT NOT NULL,
            passed INTEGER NOT NULL,
            summary TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (story_id, decision_kind, attempt_nr)
        );

        CREATE TABLE IF NOT EXISTS stories (
            story_uuid TEXT NOT NULL,
            project_key TEXT NOT NULL,
            story_number INTEGER NOT NULL,
            story_display_id TEXT NOT NULL,
            title TEXT NOT NULL,
            story_type TEXT NOT NULL,
            status TEXT NOT NULL,
            size TEXT NOT NULL,
            mode TEXT,
            epic TEXT NOT NULL,
            module TEXT NOT NULL,
            participating_repos_json TEXT NOT NULL,
            change_impact TEXT NOT NULL,
            concept_quality TEXT NOT NULL,
            owner TEXT NOT NULL,
            risk TEXT NOT NULL,
            blocker TEXT,
            labels_json TEXT NOT NULL,
            wave INTEGER NOT NULL,
            critical_path INTEGER NOT NULL,
            created_at TEXT,
            completed_at TEXT,
            PRIMARY KEY (story_uuid),
            UNIQUE (story_display_id),
            -- AG3-050 A3: project-scoped UNIQUE so story_dependencies can use a
            -- COMPOSITE FK (project_key, story_id)->(project_key,
            -- story_display_id) and reject cross-project edges fail-closed.
            UNIQUE (project_key, story_display_id),
            UNIQUE (project_key, story_number)
        );

        CREATE INDEX IF NOT EXISTS stories_project_key_idx
            ON stories (project_key);

        CREATE INDEX IF NOT EXISTS stories_project_key_number_idx
            ON stories (project_key, story_number);

        -- AG3-096 (FK-77): task-management canonical state. Tasks are not
        -- pipeline-managed; this schema stores only task state and typed links.
        CREATE TABLE IF NOT EXISTS tm_tasks (
            project_key TEXT NOT NULL,
            task_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('reminder', 'actionable')),
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            priority TEXT NOT NULL CHECK (priority IN ('low', 'normal', 'high')),
            status TEXT NOT NULL CHECK (status IN ('open', 'done', 'dismissed')),
            origin TEXT NOT NULL CHECK (origin IN (
                'closure', 'verify', 'governance', 'human'
            )),
            source_story_id TEXT,
            execution_report_ref TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT CHECK (resolved_by IS NULL OR resolved_by IN ('human', 'agent')),
            PRIMARY KEY (project_key, task_id),
            CHECK (
                length(task_id) >= 12
                AND substr(task_id, 1, 3) = 'TM-'
                AND substr(task_id, 4, 4) NOT GLOB '*[^0-9]*'
                AND substr(task_id, 8, 1) = '-'
                AND length(substr(task_id, 9)) >= 4
                AND substr(task_id, 9) NOT GLOB '*[^0-9]*'
            ),
            CHECK (
                (status = 'open' AND resolved_at IS NULL AND resolved_by IS NULL)
                OR (
                    status IN ('done', 'dismissed')
                    AND resolved_at IS NOT NULL
                    AND resolved_by IS NOT NULL
                )
            )
        );

        CREATE TABLE IF NOT EXISTS tm_task_links (
            project_key TEXT NOT NULL,
            task_id TEXT NOT NULL,
            target_kind TEXT NOT NULL CHECK (target_kind IN ('task', 'story')),
            target_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN (
                'relates_to', 'spawned_story', 'duplicate_of'
            )),
            PRIMARY KEY (project_key, task_id, target_kind, target_id, kind),
            FOREIGN KEY (project_key, task_id)
                REFERENCES tm_tasks(project_key, task_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS tm_task_links_target_idx
            ON tm_task_links (project_key, target_kind, target_id);
        """
    )
    _ensure_schema_core_tables_b(conn)


def _ensure_schema_core_tables_b(conn: sqlite3.Connection) -> None:
    """Create story-spec, artifact, and QA tables (schema part 1b).

    Split from ``_ensure_schema_runtime_tables`` to keep each function below the
    S138 300-LOC limit.  Pure structural split — idempotent ``executescript``.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS story_specifications (
            story_uuid TEXT NOT NULL,
            need TEXT,
            solution TEXT,
            acceptance_json TEXT NOT NULL,
            definition_of_done_json TEXT,
            concept_refs_json TEXT,
            guardrail_refs_json TEXT,
            external_sources_json TEXT,
            PRIMARY KEY (story_uuid)
        );

        -- AG3-140 (unified idempotency contract): test-parallel mirror of the
        -- control_plane_operations inflight-operation-record. Postgres is the
        -- canonical truth (K5); this SQLite mirror exists ONLY so the
        -- guard-counter's atomic single-transaction record (increment +
        -- idempotency record in ONE connection) keeps its unit-test parity after
        -- the record moves off the retired idempotency_keys table onto the one
        -- consolidated record. Columns mirror postgres_schema.sql EXACTLY
        -- (story_id nullable; request_body_hash additive). The control-plane
        -- RUNTIME never uses SQLite (Postgres-only), so no runtime claim/finalize
        -- global_row functions are mirrored here -- only the table shape the
        -- co-transactional guard-counter writer needs.
        CREATE TABLE IF NOT EXISTS control_plane_operations (
            op_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            story_id TEXT,
            run_id TEXT,
            session_id TEXT,
            operation_kind TEXT NOT NULL,
            phase TEXT,
            status TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            claimed_by TEXT,
            claimed_at TEXT,
            operation_epoch INTEGER,
            backend_instance_id TEXT,
            instance_incarnation INTEGER,
            declared_serialization_scope TEXT,
            finalized_at TEXT,
            request_body_hash TEXT
        );

        CREATE INDEX IF NOT EXISTS control_plane_operations_run_idx
            ON control_plane_operations (project_key, story_id, run_id);

        CREATE TABLE IF NOT EXISTS artifact_envelopes (
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            schema_version TEXT NOT NULL,
            producer_type TEXT NOT NULL CHECK (producer_type IN ('WORKER', 'LLM_REVIEWER', 'DETERMINISTIC')),
            producer_id TEXT NOT NULL,
            producer_name TEXT NOT NULL,
            producer_version TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            status TEXT NOT NULL,
            -- AG3-015: 'prompt_audit' added (FK-44 §44.6). Kept in lockstep
            -- with postgres_schema.sql + artifact_repository -- no second,
            -- competing DDL truth.
            artifact_class TEXT NOT NULL CHECK (artifact_class IN (
                'worker', 'qa', 'pipeline', 'telemetry', 'governance',
                'entwurf', 'handover', 'adversarial_test_sandbox',
                'prompt_audit'
            )),
            payload_json TEXT,
            PRIMARY KEY (story_id, run_id, stage, attempt, artifact_class, producer_name)
        );

        CREATE INDEX IF NOT EXISTS artifact_envelopes_story_run_stage_attempt_idx
            ON artifact_envelopes (story_id, run_id, stage, attempt);

        -- AG3-031 Pass-2 FK-30 correction 2026-05-24: schema corrected to
        -- (project_key, hook_event_name, matcher, command) per FK-30 §30.3.1.
        CREATE TABLE IF NOT EXISTS governance_hook_registrations (
            project_key      TEXT NOT NULL,
            hook_event_name  TEXT NOT NULL CHECK (hook_event_name IN ('PreToolUse','PostToolUse','PostToolUseFailure')),
            matcher          TEXT NOT NULL,
            command          TEXT NOT NULL,
            registered_at    TEXT NOT NULL,
            PRIMARY KEY (project_key, hook_event_name, matcher, command)
        );

        -- AG3-035 finding B: qa_stage_results/qa_findings DDL moved here from
        -- projection_repositories._ensure_sqlite_qa_schema.
        -- The schema owner for SQLite DDL is sqlite_store (SINGLE SOURCE OF TRUTH).
        -- Symmetric to the Postgres schema (postgres_schema.sql §69.6/§69.7).
        CREATE TABLE IF NOT EXISTS qa_stage_results (
            project_key      TEXT NOT NULL,
            story_id         TEXT NOT NULL,
            run_id           TEXT NOT NULL,
            attempt_no       INTEGER NOT NULL,
            stage_id         TEXT NOT NULL,
            layer            TEXT NOT NULL,
            producer_component TEXT NOT NULL,
            status           TEXT NOT NULL,
            blocking         INTEGER NOT NULL,
            total_checks     INTEGER NOT NULL,
            failed_checks    INTEGER NOT NULL,
            warning_checks   INTEGER NOT NULL,
            artifact_id      TEXT NOT NULL,
            recorded_at      TEXT NOT NULL,
            PRIMARY KEY (project_key, run_id, attempt_no, stage_id)
        );

        CREATE TABLE IF NOT EXISTS qa_findings (
            project_key      TEXT NOT NULL,
            story_id         TEXT NOT NULL,
            run_id           TEXT NOT NULL,
            attempt_no       INTEGER NOT NULL,
            stage_id         TEXT NOT NULL,
            finding_id       TEXT NOT NULL,
            check_id         TEXT NOT NULL,
            status           TEXT NOT NULL,
            severity         TEXT NOT NULL,
            blocking         INTEGER NOT NULL,
            source_component TEXT NOT NULL,
            artifact_id      TEXT NOT NULL,
            occurred_at      TEXT NOT NULL,
            category         TEXT,
            reason           TEXT,
            description      TEXT,
            detail           TEXT,
            metadata_json    TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (project_key, run_id, attempt_no, stage_id, finding_id)
        );

        -- AG3-108 (FK-69 §69.15): qa_check_outcomes. Schema-Owner verify-system,
        -- DB-Owner telemetry-and-events via ProjectionAccessor / FacadeQACheckOutcomesRepository.
        -- Records EVERY executed QA check: triggered (finding produced), clean (PASS),
        -- or overridden (suppressed). Composite PK enforces uniqueness per
        -- (project, run, stage, attempt, check).
        CREATE TABLE IF NOT EXISTS qa_check_outcomes (
            project_key          TEXT NOT NULL,
            story_id             TEXT NOT NULL,
            run_id               TEXT NOT NULL,
            stage_id             TEXT NOT NULL,
            attempt_no           INTEGER NOT NULL,
            check_id             TEXT NOT NULL,
            outcome              TEXT NOT NULL,
            occurred_at          TEXT NOT NULL,
            check_proposal_ref   TEXT,
            override_id          TEXT,
            PRIMARY KEY (project_key, run_id, stage_id, attempt_no, check_id)
        );

        -- AG3-037 (FK-68 §68.8): governance risk window. Schema-Owner
        -- telemetry-and-events, DB-Owner telemetry-and-events via
        -- ProjectionAccessor.record_risk_window_event. Append-only rolling
        -- window of NormalizedEvents the (out-of-scope) GovernanceObserver
        -- later scores. event_id is unique within a run.
        CREATE TABLE IF NOT EXISTS risk_window (
            project_key       TEXT NOT NULL,
            story_id          TEXT NOT NULL,
            run_id            TEXT NOT NULL,
            event_id          TEXT NOT NULL,
            risk_category     TEXT NOT NULL,
            severity          TEXT NOT NULL,
            observed_at       TEXT NOT NULL,
            source_event_type TEXT NOT NULL,
            payload_excerpt_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (project_key, run_id, event_id)
        );
        """
    )
    _ensure_runtime_tables_part2(conn)


def _ensure_runtime_tables_part2(conn: sqlite3.Connection) -> None:
    """Create failure-corpus incident tables (schema part 2b).

    Split out of ``_ensure_schema_runtime_tables`` so neither function exceeds the
    300-LOC limit (python:S138, Codex/Sonar): the AG3-028 failure-corpus DDL
    (fc_incidents, fc_incident_counters, element-type triggers) pushed the combined
    function over the threshold. Pure structural split — identical DDL, two
    idempotent ``executescript`` calls.
    """
    conn.executescript(
        """
        -- AG3-028 (FK-41 §41.3.1, FK-69): fc_incidents. Schema owner
        -- failure-corpus, DB owner telemetry-and-events via ProjectionAccessor.
        -- Append-only (exactly one record per incident_id). Schema exactly per
        -- FK-41 §41.3.1 (Codex-r1 remediation 2026-06-01): project_key NOT NULL,
        -- incident_id PK in the FC-YYYY-NNNN format, run_id NOT NULL, role CHECK,
        -- phase/model/symptom NOT NULL, evidence_json = list of strings.
        -- Symmetric to postgres_schema.sql.
        CREATE TABLE IF NOT EXISTS fc_incidents (
            project_key      TEXT NOT NULL,
            incident_id      TEXT NOT NULL,
            run_id           TEXT NOT NULL,
            story_id         TEXT NOT NULL,
            category         TEXT NOT NULL CHECK (category IN (
                'scope_drift', 'architecture_violation', 'evidence_fabrication',
                'hallucination', 'test_omission', 'assertion_weakness',
                'unsafe_refactor', 'policy_violation', 'tool_misuse',
                'state_desync', 'requirements_miss', 'review_evasion'
            )),
            severity         TEXT NOT NULL CHECK (severity IN (
                'low', 'medium', 'high', 'critical'
            )),
            phase            TEXT NOT NULL,
            role             TEXT NOT NULL CHECK (role IN (
                'worker', 'qa', 'governance'
            )),
            model            TEXT NOT NULL,
            symptom          TEXT NOT NULL,
            evidence_json    TEXT NOT NULL,
            recorded_at      TEXT NOT NULL,
            incident_status  TEXT NOT NULL DEFAULT 'observed' CHECK (incident_status IN (
                'observed', 'promoted', 'closed_one_off', 'archived'
            )),
            tags             TEXT,
            impact           TEXT,
            pattern_ref      TEXT,
            -- Codex-r2 (user decision 2026-06-01): incident_id is GLOBALLY
            -- unique (no project segment, no per-project numbering).
            -- PK = incident_id alone; project_key stays a NOT-NULL column and
            -- read/purge still mandatorily filter by project_key (r1 fix).
            -- The FC-YYYY-NNNN numbers come from a global per-year
            -- counter (fc_incident_counters, keyed on year alone).
            -- incident_id == FC-YYYY-NNNN (NNNN >= 4 digits, DIGITS ONLY). The
            -- prefix GLOB enforces FC-YYYY- + >=4 digits; the NOT GLOB on the
            -- sequence (from pos. 9) forbids a non-digit suffix like
            -- "...0001x". Mirrors the Pydantic validator (year 4 digits,
            -- sequence at least 4 digits, digits only).
            CONSTRAINT fc_incidents_id_format
                CHECK (incident_id GLOB
                       'FC-[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]*'
                       AND substr(incident_id, 9) NOT GLOB '*[^0-9]*'),
            -- evidence_json = JSON array. The array type is enforced via CHECK;
            -- the element type (list[str], FK-41 §41.4.1) on the DB side via a
            -- BEFORE trigger (json_each, see below) — a CHECK cannot validate
            -- JSON array elements element-wise. This makes the DB symmetric to
            -- the Postgres jsonpath CHECK and fail-closed (even against direct inserts).
            CONSTRAINT fc_incidents_evidence_is_array
                CHECK (json_valid(evidence_json)
                       AND json_type(evidence_json) = 'array'),
            -- tags is optional; when set, a JSON array (element type
            -- list[str] is enforced by the BEFORE trigger below). NULL allowed. Without
            -- this CHECK, json_each would wrongly wave a scalar/object through as
            -- text rows (Codex-r6).
            CONSTRAINT fc_incidents_tags_is_array
                CHECK (tags IS NULL
                       OR (json_valid(tags) AND json_type(tags) = 'array')),
            PRIMARY KEY (incident_id)
        );

        CREATE INDEX IF NOT EXISTS idx_fc_incidents_project_story_run
            ON fc_incidents (project_key, story_id, run_id);

        CREATE INDEX IF NOT EXISTS idx_fc_incidents_incident_status
            ON fc_incidents (incident_status);

        -- AG3-028 (Codex-r5): evidence_json/tags MUST be JSON arrays OF STRINGS
        -- (FK-41 §41.4.1 list[str]). A CHECK cannot iterate array elements;
        -- a BEFORE trigger with json_each can. RAISE(ABORT) makes the
        -- insert/update fail-closed on a non-string element — at the DB level,
        -- independent of Pydantic (covers direct inserts; symmetric to the
        -- Postgres jsonpath CHECK).
        CREATE TRIGGER IF NOT EXISTS trg_fc_incidents_strarray_insert
        BEFORE INSERT ON fc_incidents
        WHEN EXISTS (SELECT 1 FROM json_each(NEW.evidence_json) AS e
                     WHERE e.type <> 'text')
          OR (NEW.tags IS NOT NULL
              AND EXISTS (SELECT 1 FROM json_each(NEW.tags) AS t
                          WHERE t.type <> 'text'))
        BEGIN
            SELECT RAISE(ABORT,
                'evidence_json/tags must be a JSON array of strings (FK-41 §41.4.1)');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_fc_incidents_strarray_update
        BEFORE UPDATE ON fc_incidents
        WHEN EXISTS (SELECT 1 FROM json_each(NEW.evidence_json) AS e
                     WHERE e.type <> 'text')
          OR (NEW.tags IS NOT NULL
              AND EXISTS (SELECT 1 FROM json_each(NEW.tags) AS t
                          WHERE t.type <> 'text'))
        BEGIN
            SELECT RAISE(ABORT,
                'evidence_json/tags must be a JSON array of strings (FK-41 §41.4.1)');
        END;

        -- AG3-028 (Codex-r2): GLOBAL per-year counter for the globally
        -- unique FC-YYYY-NNNN allocation (PK = year alone, NO
        -- project_key). Race-safe in ONE atomic UPSERT with RETURNING
        -- (SQLite >= 3.35), serialized under BEGIN IMMEDIATE.
        CREATE TABLE IF NOT EXISTS fc_incident_counters (
            year              INTEGER NOT NULL,
            next_seq          INTEGER NOT NULL,
            PRIMARY KEY (year)
        );
        """
    )
    _ensure_runtime_tables_part2b(conn)


def _ensure_runtime_tables_part2b(conn: sqlite3.Connection) -> None:
    """Create lock, binding, governance and custom-field tables (schema part 2b-II).

    Split out of ``_ensure_runtime_tables_part2`` so neither function exceeds the
    300-LOC limit (python:S138, Codex/Sonar). Pure structural split — identical
    DDL, idempotent ``executescript`` call.
    """
    conn.executescript(
        """
        -- AG3-031 Pass-7: DDL consolidated from lock_record_repository.py into
        -- the canonical schema bootstrap (symmetric with Postgres).
        -- PK corrected to (project_key, story_id, run_id, lock_type) per
        -- FK-22 §22.7 (Pass-5 corrective, SCHEMA_VERSION 3.6.0).
        CREATE TABLE IF NOT EXISTS story_execution_locks (
            project_key          TEXT NOT NULL,
            story_id             TEXT NOT NULL,
            run_id               TEXT NOT NULL,
            lock_type            TEXT NOT NULL,
            status               TEXT NOT NULL,
            worktree_roots_json  TEXT NOT NULL,
            binding_version      TEXT NOT NULL,
            activated_at         TEXT NOT NULL,
            updated_at           TEXT NOT NULL,
            deactivated_at       TEXT,
            PRIMARY KEY (project_key, story_id, run_id, lock_type)
        );

        -- AG3-048 (FK-43 §43.4.1, bc-cut-decisions.md §BC 11): skill_bindings.
        -- Schema owner agent-skills (SkillBinding entity, AG3-027); DB owner
        -- state_backend. Postgres is canonical, this SQLite schema is the
        -- test-parallel path with IDENTICAL DDL (symmetric to
        -- postgres_schema.sql). Columns mirror the SkillBinding model EXACTLY
        -- (no manifest_digest, the model owns the shape). Upsert on
        -- (project_key, skill_name). status covers ALL SIX
        -- SkillLifecycleStatus values (FAIL-CLOSED CHECK).
        CREATE TABLE IF NOT EXISTS skill_bindings (
            binding_id       TEXT NOT NULL,
            project_key      TEXT NOT NULL,
            skill_name       TEXT NOT NULL,
            bundle_id        TEXT NOT NULL,
            bundle_version   TEXT NOT NULL,
            target_path      TEXT NOT NULL,
            binding_mode     TEXT NOT NULL CHECK (binding_mode IN ('SYMLINK', 'JUNCTION')),
            status           TEXT NOT NULL CHECK (status IN (
                'REQUESTED', 'PROFILE_RESOLVED', 'BUNDLE_SELECTED',
                'BOUND', 'VERIFIED', 'REJECTED'
            )),
            pinned_at        TEXT NOT NULL,
            PRIMARY KEY (binding_id),
            UNIQUE (project_key, skill_name)
        );

        CREATE INDEX IF NOT EXISTS idx_skill_bindings_project_skill
            ON skill_bindings (project_key, skill_name);

        -- AG3-032 (FK-55 §55.8 / §55.10.5, FK-31 §31.2.7): governance_freeze_records.
        -- Test-parallel path with IDENTICAL DDL to postgres_schema.sql (Postgres
        -- is canonical). Canonical (truth) side of the dual conflict-freeze
        -- materialization; the local .agentkit/governance/freeze.json is the
        -- hook-fast export with an identical freeze_version. Active members are
        -- keyed independently by (story_id, kind).
        CREATE TABLE IF NOT EXISTS governance_freeze_records (
            story_id        TEXT NOT NULL,
            frozen_at       TEXT NOT NULL,
            freeze_reason   TEXT NOT NULL,
            freeze_version  INTEGER NOT NULL,
            kind            TEXT NOT NULL DEFAULT 'conflict_freeze' CHECK (
                kind IN (
                    'conflict_freeze', 'split_admin_freeze',
                    'reconcile_repair', 'contested_local_writes'
                )
            ),
            freeze_epoch    TEXT NOT NULL CHECK (
                freeze_epoch NOT GLOB '*[^0-9]*'
                AND substr(freeze_epoch, 1, 1) BETWEEN '1' AND '9'
            ),
            PRIMARY KEY (story_id, kind)
        );

        CREATE TABLE IF NOT EXISTS governance_freeze_audit_records (
            story_id        TEXT NOT NULL,
            freeze_epoch    TEXT NOT NULL CHECK (
                freeze_epoch NOT GLOB '*[^0-9]*'
                AND substr(freeze_epoch, 1, 1) BETWEEN '1' AND '9'
            ),
            kind            TEXT NOT NULL CHECK (
                kind IN (
                    'conflict_freeze', 'split_admin_freeze',
                    'reconcile_repair', 'contested_local_writes'
                )
            ),
            frozen_at       TEXT NOT NULL,
            freeze_reason   TEXT NOT NULL,
            freeze_version  INTEGER NOT NULL,
            PRIMARY KEY (story_id, freeze_epoch)
        );

        CREATE TABLE IF NOT EXISTS guard_decisions (
            project_key       TEXT NOT NULL,
            story_id          TEXT NOT NULL,
            run_id            TEXT NOT NULL,
            flow_id           TEXT NOT NULL,
            guard_decision_id TEXT NOT NULL,
            guard_key         TEXT NOT NULL,
            outcome           TEXT NOT NULL CHECK (outcome IN (
                'PASS', 'WARNING', 'ERROR'
            )),
            decided_at        TEXT NOT NULL,
            node_id           TEXT,
            reason            TEXT,
            evidence_ref      TEXT,
            PRIMARY KEY (project_key, run_id, guard_decision_id)
        );

        CREATE INDEX IF NOT EXISTS idx_guard_decisions_story_run
            ON guard_decisions (project_key, story_id, run_id);

        CREATE TABLE IF NOT EXISTS conflict_freeze_proofs (
            project_key             TEXT NOT NULL,
            story_id                TEXT NOT NULL,
            run_id                  TEXT NOT NULL,
            proof_id                TEXT NOT NULL,
            activated_at            TEXT NOT NULL,
            blocked_principal       TEXT NOT NULL,
            resolution_service_path TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id, run_id, proof_id)
        );

        CREATE INDEX IF NOT EXISTS idx_conflict_freeze_proofs_story_run
            ON conflict_freeze_proofs (project_key, story_id, run_id);

        CREATE TABLE IF NOT EXISTS story_custom_field_definitions (
            project_key                 TEXT NOT NULL,
            field_key                   TEXT NOT NULL,
            display_name                TEXT NOT NULL,
            field_type                  TEXT NOT NULL CHECK (field_type IN (
                'text', 'number', 'boolean', 'enum', 'date', 'json'
            )),
            provider                    TEXT NOT NULL,
            provider_field_ref          TEXT NOT NULL,
            is_required                 INTEGER NOT NULL CHECK (is_required IN (0, 1)),
            is_writable_by_agentkit     INTEGER NOT NULL CHECK (
                is_writable_by_agentkit IN (0, 1)
            ),
            allowed_values              TEXT NOT NULL,
            PRIMARY KEY (project_key, field_key)
        );

        CREATE TABLE IF NOT EXISTS story_custom_field_values (
            project_key             TEXT NOT NULL,
            story_id                TEXT NOT NULL,
            field_key               TEXT NOT NULL,
            value                   TEXT NOT NULL,
            value_status            TEXT NOT NULL CHECK (value_status IN (
                'present', 'missing', 'invalid', 'conflict'
            )),
            source                  TEXT NOT NULL CHECK (source IN (
                'provider', 'agentkit', 'human'
            )),
            last_synced_at          TEXT,
            last_written_by         TEXT,
            provider_sync_status    TEXT NOT NULL CHECK (provider_sync_status IN (
                'in_sync', 'pending', 'failed', 'not_writable'
            )),
            conflict_detected       INTEGER NOT NULL CHECK (
                conflict_detected IN (0, 1)
            ),
            last_sync_attempt_at    TEXT,
            PRIMARY KEY (project_key, story_id, field_key),
            FOREIGN KEY (project_key, field_key)
                REFERENCES story_custom_field_definitions(project_key, field_key)
        );

        -- AG3-034 (FK-24 §24.3.3, FK-22 §22.3.1 Check 10): project_mode_lock.
        -- Test-parallel path with IDENTICAL DDL to postgres_schema.sql (Postgres
        -- is canonical). Project-wide mode lock for the fast/standard mutual
        -- exclusion; AG3-034 provides ONLY the read path for preflight check 10
        -- (atomic setting = AG3-018 follow-up, story.md §2.1.2 / §2.2). active_mode
        -- lives on the decoupled fast/standard-mode axis (WireStoryMode,
        -- FK-24 §24.3.3), NOT on the execution_route axis. NULL = idle.
        -- holder_count >= 0.
        CREATE TABLE IF NOT EXISTS project_mode_lock (
            project_key    TEXT NOT NULL,
            active_mode    TEXT CHECK (active_mode IS NULL OR active_mode IN (
                'standard', 'fast'
            )),
            holder_count   INTEGER NOT NULL DEFAULT 0 CHECK (holder_count >= 0),
            updated_at     TEXT NOT NULL,
            PRIMARY KEY (project_key)
        );

        -- AG3-131 test-parallel schema. Postgres remains canonical.
        CREATE TABLE IF NOT EXISTS project_mode_lock_holders (
            project_key    TEXT NOT NULL,
            story_id       TEXT NOT NULL,
            run_id         TEXT NOT NULL,
            mode           TEXT NOT NULL CHECK (mode IN ('standard', 'fast')),
            acquired_at    TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id, run_id),
            FOREIGN KEY (project_key) REFERENCES project_mode_lock(project_key)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS ccag_permission_requests (
            request_id          TEXT PRIMARY KEY,
            project_key         TEXT NOT NULL,
            story_id            TEXT NOT NULL,
            run_id              TEXT NOT NULL,
            principal_type      TEXT NOT NULL,
            tool_name           TEXT NOT NULL,
            operation_class     TEXT NOT NULL,
            path_classes        TEXT NOT NULL,
            request_fingerprint TEXT NOT NULL,
            status              TEXT NOT NULL CHECK (status IN (
                'pending', 'approved', 'denied', 'expired'
            )),
            requested_at        TEXT NOT NULL,
            expires_at          TEXT NOT NULL,
            resolution          TEXT,
            decided_at          TEXT,
            decision_note       TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS ccag_permission_requests_scope_idx
            ON ccag_permission_requests (project_key, story_id, run_id, status);

        CREATE TABLE IF NOT EXISTS ccag_permission_leases (
            lease_id            TEXT PRIMARY KEY,
            request_ref         TEXT NOT NULL REFERENCES ccag_permission_requests(request_id),
            project_key         TEXT NOT NULL,
            story_id            TEXT NOT NULL,
            run_id              TEXT NOT NULL,
            principal_type      TEXT NOT NULL,
            tool_name           TEXT NOT NULL,
            operation_class     TEXT NOT NULL,
            path_classes        TEXT NOT NULL,
            request_fingerprint TEXT NOT NULL,
            max_uses            INTEGER NOT NULL DEFAULT 1 CHECK (max_uses > 0),
            consumed            INTEGER NOT NULL DEFAULT 0 CHECK (
                consumed >= 0 AND consumed <= max_uses
            ),
            issued_at           TEXT NOT NULL,
            expires_at          TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ccag_permission_leases_binding_idx
            ON ccag_permission_leases (
                project_key, story_id, run_id, principal_type, tool_name,
                operation_class, request_fingerprint
            );

        -- AG3-039 (FK-50 §50.3 CP 7, formal.installer.entities
        -- §project-registration): project_registry. Test-parallel path to
        -- postgres_schema.sql (Postgres is canonical).
        -- Canonical state-backend registration for installer checkpoint 7.
        -- project_root is UNIQUE (exactly one registration per filesystem root);
        -- runtime_profile is restricted to the RuntimeProfile wire values
        -- (core | are). last_verified_at / last_upgraded_at stay NULL until
        -- verify-project / an upgrade rerun set them. The time columns are
        -- ISO-8601 TEXT, consistent with the SQLite timestamp convention of the
        -- other AK3 tables (SQLite has no native timestamptz affinity); the
        -- canonical Postgres path uses TIMESTAMPTZ instead (story §2.1.1). The
        -- mapper round-trips datetime against both backends.
        CREATE TABLE IF NOT EXISTS project_registry (
            project_key      TEXT NOT NULL,
            project_root     TEXT NOT NULL,
            github_owner     TEXT NOT NULL,
            github_repo      TEXT NOT NULL,
            runtime_profile  TEXT NOT NULL CHECK (runtime_profile IN (
                'core', 'are'
            )),
            config_version   TEXT NOT NULL,
            config_digest    TEXT NOT NULL,
            registered_at    TEXT NOT NULL,
            last_verified_at TEXT,
            last_upgraded_at TEXT,
            PRIMARY KEY (project_key),
            UNIQUE (project_root)
        );
        """
    )
    _ensure_runtime_tables_part3(conn)


def _ensure_runtime_tables_part3(conn: sqlite3.Connection) -> None:
    """Create the AG3-040 failure-corpus aggregate tables (schema part 2c).

    Split out of ``_ensure_runtime_tables_part2`` so neither function exceeds the
    300-LOC limit (python:S138, Codex/Sonar): the AG3-040 Sub-Block (b) DDL
    (fc_patterns, fc_check_proposals incl. element-type trigger) pushed part2 over
    the threshold. Pure structural split — identical DDL, idempotent
    ``executescript`` call. Test-parallel path to ``postgres_schema.sql``
    (Postgres is canonical; FK-41 §41.3.2/§41.3.3, FK-69 §69.3).
    """
    conn.executescript(
        """
        -- AG3-040 Sub-Block (b) (FK-41 §41.3.2, FK-69 §69.3): fc_patterns.
        -- Schema owner failure-corpus. Test-parallel path with IDENTICAL
        -- semantics to postgres_schema.sql (Postgres is canonical). status =
        -- pattern-status (4 values), category = FailureCategory (12 values),
        -- promotion_rule/risk_level with the FK-41 enums. incident_refs = JSON
        -- array of incident_id strings (element type list[str] via BEFORE trigger,
        -- since a CHECK cannot iterate array elements). ONLY table +
        -- repository skeleton; the writer (PatternPromotion) is Out of Scope.
        CREATE TABLE IF NOT EXISTS fc_patterns (
            pattern_id        TEXT NOT NULL,
            project_key       TEXT NOT NULL,
            status            TEXT NOT NULL CHECK (status IN (
                'candidate', 'accepted', 'rejected', 'retired'
            )),
            category          TEXT NOT NULL CHECK (category IN (
                'scope_drift', 'architecture_violation', 'evidence_fabrication',
                'hallucination', 'test_omission', 'assertion_weakness',
                'unsafe_refactor', 'policy_violation', 'tool_misuse',
                'state_desync', 'requirements_miss', 'review_evasion'
            )),
            invariant         TEXT NOT NULL,
            incident_refs     TEXT NOT NULL,
            promotion_rule    TEXT NOT NULL CHECK (promotion_rule IN (
                'repetition', 'high_severity', 'favorable_checkability'
            )),
            risk_level        TEXT NOT NULL CHECK (risk_level IN (
                'medium', 'high', 'critical'
            )),
            incident_count    INTEGER NOT NULL,
            confirmed_at      TEXT,
            confirmed_by      TEXT CHECK (confirmed_by IS NULL OR confirmed_by = 'human'),
            owner             TEXT,
            -- check_ref is an FK to fc_check_proposals(check_id) (FK-41 §41.3.2:234).
            -- Circular FK with fc_check_proposals.pattern_ref: SQLite allows the
            -- forward reference in CREATE TABLE (the FK target is resolved only on
            -- use), and _connect sets PRAGMA foreign_keys = ON (enforces
            -- the FK identically to pattern_ref). Both refs are nullable.
            check_ref         TEXT REFERENCES fc_check_proposals(check_id),
            retired_at        TEXT,
            -- pattern_id == FP-NNNN (NNNN >= 4 digits, DIGITS ONLY). The
            -- prefix GLOB enforces FP- + >=4 digits; the NOT GLOB from pos. 4
            -- forbids a non-digit suffix.
            CONSTRAINT fc_patterns_id_format
                CHECK (pattern_id GLOB 'FP-[0-9][0-9][0-9][0-9]*'
                       AND substr(pattern_id, 4) NOT GLOB '*[^0-9]*'),
            -- incident_refs = JSON array (array type via CHECK; element type
            -- list[str] enforced by the BEFORE trigger below).
            CONSTRAINT fc_patterns_incident_refs_is_array
                CHECK (json_valid(incident_refs)
                       AND json_type(incident_refs) = 'array'),
            -- FK-41 §41.3.2:239: no pattern transitions into 'accepted' without
            -- confirmed_by = 'human' (FAIL-CLOSED, lifecycle invariant;
            -- mirrors Postgres fc_patterns_accepted_human + Pydantic validator).
            CONSTRAINT fc_patterns_accepted_human
                CHECK (status <> 'accepted' OR confirmed_by IS 'human'),
            PRIMARY KEY (pattern_id)
        );

        CREATE INDEX IF NOT EXISTS idx_fc_patterns_project
            ON fc_patterns (project_key);

        CREATE INDEX IF NOT EXISTS idx_fc_patterns_status
            ON fc_patterns (status);

        -- incident_refs MUST be a JSON array OF STRINGS (FK-41 §41.3.2).
        -- Symmetric to the Postgres jsonpath CHECK + fc_incidents trigger.
        CREATE TRIGGER IF NOT EXISTS trg_fc_patterns_strarray_insert
        BEFORE INSERT ON fc_patterns
        WHEN EXISTS (SELECT 1 FROM json_each(NEW.incident_refs) AS e
                     WHERE e.type <> 'text')
        BEGIN
            SELECT RAISE(ABORT,
                'incident_refs must be a JSON array of strings (FK-41 §41.3.2)');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_fc_patterns_strarray_update
        BEFORE UPDATE ON fc_patterns
        WHEN EXISTS (SELECT 1 FROM json_each(NEW.incident_refs) AS e
                     WHERE e.type <> 'text')
        BEGIN
            SELECT RAISE(ABORT,
                'incident_refs must be a JSON array of strings (FK-41 §41.3.2)');
        END;

        -- AG3-040 Sub-Block (b) (FK-41 §41.3.3, FK-69 §69.3): fc_check_proposals.
        -- Schema owner failure-corpus. Test-parallel path with IDENTICAL
        -- semantics to postgres_schema.sql. status = check-status (5 values),
        -- check_type = 6 FK-41 values, false_positive_risk = low|medium|high.
        -- pattern_ref is an FK to fc_patterns(pattern_id). positive_/negative_
        -- fixtures = JSON arrays. ONLY table + repository skeleton; the writer
        -- (CheckFactory) is Out of Scope.
        CREATE TABLE IF NOT EXISTS fc_check_proposals (
            check_id              TEXT NOT NULL,
            project_key           TEXT NOT NULL,
            status                TEXT NOT NULL CHECK (status IN (
                'draft', 'approved', 'active', 'rejected', 'retired'
            )),
            pattern_ref           TEXT NOT NULL REFERENCES fc_patterns(pattern_id),
            invariant             TEXT NOT NULL,
            check_type            TEXT NOT NULL CHECK (check_type IN (
                'Changed-File-Policy', 'Artifact-Completeness', 'Test-Obligation',
                'Sensitive-Path-Guard', 'Forbidden-Dependency', 'Fixture-Replay'
            )),
            pipeline_stage        TEXT NOT NULL,
            pipeline_layer        INTEGER NOT NULL,
            owner                 TEXT NOT NULL,
            false_positive_risk   TEXT NOT NULL CHECK (false_positive_risk IN (
                'low', 'medium', 'high'
            )),
            positive_fixtures     TEXT NOT NULL,
            negative_fixtures     TEXT NOT NULL,
            created_at            TEXT NOT NULL,
            approved_at           TEXT,
            approved_by           TEXT CHECK (approved_by IS NULL OR approved_by = 'human'),
            rejected_reason       TEXT,
            effectiveness_last_checked_at TEXT,
            true_positives_90d    INTEGER,
            false_positives_90d   INTEGER,
            no_findings_90d       INTEGER,
            -- check_id == CHK-NNNN (NNNN >= 4 digits, DIGITS ONLY).
            CONSTRAINT fc_check_proposals_id_format
                CHECK (check_id GLOB 'CHK-[0-9][0-9][0-9][0-9]*'
                       AND substr(check_id, 5) NOT GLOB '*[^0-9]*'),
            -- positive_/negative_fixtures = JSON array (array type via CHECK;
            -- the {description, expected} element shape is enforced by the BEFORE
            -- trigger below, since a CHECK cannot iterate array elements).
            CONSTRAINT fc_check_proposals_positive_fixtures_is_array
                CHECK (json_valid(positive_fixtures)
                       AND json_type(positive_fixtures) = 'array'),
            CONSTRAINT fc_check_proposals_negative_fixtures_is_array
                CHECK (json_valid(negative_fixtures)
                       AND json_type(negative_fixtures) = 'array'),
            -- FK-41 §41.3.3:282: approved_by must be 'human'; 'active' inherits the
            -- requirement (forward transition from 'approved'). FAIL-CLOSED, mirrors
            -- Postgres fc_check_proposals_approved_human + Pydantic validator.
            CONSTRAINT fc_check_proposals_approved_human
                CHECK (status NOT IN ('approved', 'active')
                       OR approved_by IS 'human'),
            PRIMARY KEY (check_id)
        );

        CREATE INDEX IF NOT EXISTS idx_fc_check_proposals_project
            ON fc_check_proposals (project_key);

        CREATE INDEX IF NOT EXISTS idx_fc_check_proposals_pattern_ref
            ON fc_check_proposals (pattern_ref);

        CREATE INDEX IF NOT EXISTS idx_fc_check_proposals_status
            ON fc_check_proposals (status);

        -- positive_/negative_fixtures MUST be JSON arrays of {description,
        -- expected} objects (FK-41 §41.3.3:265-266). A CHECK cannot
        -- iterate array elements; a BEFORE trigger with json_each can.
        -- RAISE(ABORT) makes insert/update fail-closed on an element that
        -- is NOT an object or is missing a required key. This means the
        -- DB cannot hold a fixtures value that the repo decoder rejects
        -- (symmetric to the Postgres jsonpath CHECK *_fixtures_shape).
        CREATE TRIGGER IF NOT EXISTS trg_fc_check_proposals_fixtures_insert
        BEFORE INSERT ON fc_check_proposals
        WHEN EXISTS (
                 SELECT 1 FROM json_each(NEW.positive_fixtures) AS e
                 WHERE e.type <> 'object'
                    OR json_type(e.value, '$.description') IS NULL
                    OR json_type(e.value, '$.expected') IS NULL
             )
          OR EXISTS (
                 SELECT 1 FROM json_each(NEW.negative_fixtures) AS e
                 WHERE e.type <> 'object'
                    OR json_type(e.value, '$.description') IS NULL
                    OR json_type(e.value, '$.expected') IS NULL
             )
        BEGIN
            SELECT RAISE(ABORT,
                'fixtures must be a JSON array of {description, expected} objects (FK-41 §41.3.3)');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_fc_check_proposals_fixtures_update
        BEFORE UPDATE ON fc_check_proposals
        WHEN EXISTS (
                 SELECT 1 FROM json_each(NEW.positive_fixtures) AS e
                 WHERE e.type <> 'object'
                    OR json_type(e.value, '$.description') IS NULL
                    OR json_type(e.value, '$.expected') IS NULL
             )
          OR EXISTS (
                 SELECT 1 FROM json_each(NEW.negative_fixtures) AS e
                 WHERE e.type <> 'object'
                    OR json_type(e.value, '$.description') IS NULL
                    OR json_type(e.value, '$.expected') IS NULL
             )
        BEGIN
            SELECT RAISE(ABORT,
                'fixtures must be a JSON array of {description, expected} objects (FK-41 §41.3.3)');
        END;
        """
    )
    _ensure_analytics_tables(conn)


def _ensure_analytics_tables(conn: sqlite3.Connection) -> None:
    """Create the AG3-038 analytics fact tables + sync_state + scratchpad.

    SINGLE SOURCE OF TRUTH for the SQLite analytics DDL is the versioned
    migration ``state_backend/migration/versions/v_3_4_analytics.sql``, applied
    here through the ``MigrationRunner`` (FK-62 §62.4). Running it from the
    canonical schema bootstrap means the migration is wired in production — not
    dead module/test-only code — and records logical analytics version ``3.4`` in
    the idempotent ``schema_versions`` cursor (FK-62 §62.4.3). The DDL is itself
    idempotent (``CREATE TABLE IF NOT EXISTS``), so a re-run is a no-op.

    SQLite has no schema concept, so the tables carry no ``analytics.`` prefix
    and live in the active versioned schema (story §2.1.4 / §8). Timestamps are
    ISO-8601 TEXT; the mapper roundtrips ``datetime`` against both backends.

    Mandantenregel (FK-62 §62.2): project_key is the leading scope key.
    """
    from agentkit.backend.state_backend.migration import MigrationRunner

    MigrationRunner().run(conn)
