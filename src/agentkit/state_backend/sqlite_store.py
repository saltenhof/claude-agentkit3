"""SQLite-backed canonical runtime store with JSON projections.

This module is a T-bloodtype infrastructure driver.
It MUST NOT import BC-Records (A-bloodtype components).
All BC-Record <-> dict conversions live in
``agentkit.state_backend.store.mappers`` (boundary.state_backend_repository).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from agentkit.boundary.filesystem import atomic_write_json, load_json_object
from agentkit.boundary.shared.time import now_iso
from agentkit.core_types.qa_artifact_names import VERIFY_DECISION_FILE
from agentkit.exceptions import CorruptStateError
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed, versioned_sqlite_db_file
from agentkit.state_backend.paths import (
    CLOSURE_REPORT_FILE,
    CONTEXT_EXPORT_FILE,
    PHASE_STATE_EXPORT_FILE,
    state_backend_dir,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from agentkit.state_backend.scope import RuntimeStateScope

_JsonRecord = dict[str, object]


def current_db_file_name() -> str:
    """Return the versioned SQLite database filename used by this driver."""

    return versioned_sqlite_db_file()


def state_db_path_for(story_dir: Path) -> Path:
    """Return the versioned SQLite database path used by this driver."""

    return state_backend_dir(story_dir) / current_db_file_name()


def load_json_safe(path: Path) -> _JsonRecord | None:
    """Compatibility helper for non-canonical export reads."""

    return load_json_object(path)


def _write_projection(path: Path, payload: _JsonRecord) -> None:
    """Atomically write a JSON projection file, creating parent dirs as needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


def _dump_json(data: object) -> str:
    return json.dumps(data, sort_keys=True, default=str)


def _load_json(data: str | None, default: Any) -> Any:
    if data is None:
        return default
    return json.loads(data)


def _cast_json_record(value: object) -> _JsonRecord:
    return cast("_JsonRecord", value)


def _assert_sqlite_allowed() -> None:
    """Raise RuntimeError if SQLite backend is not explicitly enabled.

    Enforces the AGENTKIT_ALLOW_SQLITE=1 gating pattern (Fix E8, AG3-031 Pass-6).
    """
    if not _sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for this path. "
            f"Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )


@contextmanager
def _connect(story_dir: Path) -> Iterator[sqlite3.Connection]:
    db_path = state_db_path_for(story_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _assert_sqlite_allowed()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS story_contexts (
            story_uuid TEXT NOT NULL,
            project_key TEXT NOT NULL,
            story_number INTEGER NOT NULL,
            story_id TEXT NOT NULL,
            story_type TEXT NOT NULL,
            -- execution_route is nullable since AG3-021: non-implementing
            -- story types (concept/research) carry NULL instead of a
            -- sentinel value (siehe AG3-021 §2.1.1.1 StoryMode-Werte).
            execution_route TEXT,
            implementation_contract TEXT,
            issue_nr INTEGER,
            title TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id),
            FOREIGN KEY (project_key) REFERENCES projects(key)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_story_id_idx
            ON story_contexts (story_id);

        CREATE TABLE IF NOT EXISTS projects (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            story_id_prefix TEXT NOT NULL UNIQUE,
            configuration_json TEXT NOT NULL,
            archived_at TEXT
        );

        CREATE INDEX IF NOT EXISTS projects_archived_at_idx
            ON projects (archived_at);

        CREATE TABLE IF NOT EXISTS story_number_counters (
            project_key TEXT PRIMARY KEY,
            next_story_number INTEGER NOT NULL,
            FOREIGN KEY (project_key) REFERENCES projects(key)
        );

        -- AG3-050 (FK-02 §2.11.3, FK-18 §18.6a/§18.13): the StoryDependency edge
        -- binds to the STATIC story stammdaten (`stories`), NOT the runtime
        -- projection (`story_contexts`). story_id/depends_on_story_id hold
        -- display-ID strings, so the FK target columns are display-ID columns.
        -- A3: the FK is COMPOSITE on (project_key, story_id) ->
        -- stories(project_key, story_display_id) for BOTH endpoints, so an edge
        -- whose endpoints live in a different project is rejected fail-closed at
        -- the FK (not merely "display-ID exists somewhere"). story_display_id is
        -- chosen over story_uuid because the columns carry display-ID strings
        -- (no wire/data change), and over story_number because that would force
        -- storing numbers instead of the display ID.
        CREATE TABLE IF NOT EXISTS story_dependencies (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            depends_on_story_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_key, story_id, depends_on_story_id, kind),
            FOREIGN KEY (project_key) REFERENCES projects(key),
            FOREIGN KEY (project_key, story_id)
                REFERENCES stories(project_key, story_display_id),
            FOREIGN KEY (project_key, depends_on_story_id)
                REFERENCES stories(project_key, story_display_id)
        );

        CREATE INDEX IF NOT EXISTS story_dependencies_project_story_idx
            ON story_dependencies (project_key, story_id);

        CREATE INDEX IF NOT EXISTS story_dependencies_project_depends_idx
            ON story_dependencies (project_key, depends_on_story_id);

        CREATE TABLE IF NOT EXISTS parallelization_configs (
            project_key TEXT PRIMARY KEY,
            max_parallel_stories INTEGER NOT NULL,
            max_parallel_stories_per_repo INTEGER,
            extra_config_json TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_key) REFERENCES projects(key)
        );

        CREATE TABLE IF NOT EXISTS story_are_links (
            story_id TEXT NOT NULL,
            are_item_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            PRIMARY KEY (story_id, are_item_id, kind),
            FOREIGN KEY (story_id) REFERENCES story_contexts(story_id)
        );

        CREATE TABLE IF NOT EXISTS project_api_tokens (
            token_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            label TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            revoked_at TEXT,
            last_used_at TEXT,
            FOREIGN KEY (project_key) REFERENCES projects(key)
        );

        CREATE INDEX IF NOT EXISTS project_api_tokens_project_idx
            ON project_api_tokens (project_key);

        CREATE TABLE IF NOT EXISTS phase_states (
            story_id TEXT PRIMARY KEY,
            phase TEXT NOT NULL,
            status TEXT NOT NULL,
            paused_reason TEXT,
            review_round INTEGER NOT NULL,
            attempt_id TEXT,
            errors_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS phase_snapshots (
            story_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            status TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (story_id, phase)
        );
        """
    )
    _ensure_schema_runtime_tables(conn)
    _ensure_story_identity_migration(conn)
    _ensure_four_phase_migration(conn)


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
            consumed_at TEXT
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

        CREATE TABLE IF NOT EXISTS idempotency_keys (
            op_id TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            result_payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            PRIMARY KEY (op_id)
        );

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

        -- AG3-031 Pass-2 FK-30-Korrektur 2026-05-24: schema corrected to
        -- (project_key, hook_event_name, matcher, command) per FK-30 §30.3.1.
        CREATE TABLE IF NOT EXISTS governance_hook_registrations (
            project_key      TEXT NOT NULL,
            hook_event_name  TEXT NOT NULL CHECK (hook_event_name IN ('PreToolUse','PostToolUse')),
            matcher          TEXT NOT NULL,
            command          TEXT NOT NULL,
            registered_at    TEXT NOT NULL,
            PRIMARY KEY (project_key, hook_event_name, matcher)
        );

        -- AG3-035 Befund-B: qa_stage_results/qa_findings DDL verschoben von
        -- projection_repositories._ensure_sqlite_qa_schema hierher.
        -- Schema-Owner fuer SQLite-DDL ist sqlite_store (SINGLE SOURCE OF TRUTH).
        -- Symmetrisch zu Postgres-Schema (postgres_schema.sql §69.6/§69.7).
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
    """Create failure-corpus, lock and remaining runtime tables (schema part 2b).

    Split out of ``_ensure_schema_runtime_tables`` so neither function exceeds the
    300-LOC limit (python:S138, Codex/Sonar): the AG3-028 failure-corpus DDL
    (fc_incidents, fc_incident_counters, element-type triggers) pushed the combined
    function over the threshold. Pure structural split — identische DDL, zwei
    idempotente ``executescript``-Aufrufe.
    """
    conn.executescript(
        """
        -- AG3-028 (FK-41 §41.3.1, FK-69): fc_incidents. Schema-Owner
        -- failure-corpus, DB-Owner telemetry-and-events via ProjectionAccessor.
        -- Append-only (genau ein Datensatz pro incident_id). Schema exakt nach
        -- FK-41 §41.3.1 (Codex-r1 Remediation 2026-06-01): project_key NOT NULL,
        -- incident_id PK im Format FC-YYYY-NNNN, run_id NOT NULL, role CHECK,
        -- phase/model/symptom NOT NULL, evidence_json = Liste von Strings.
        -- Symmetrisch zu postgres_schema.sql.
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
            -- Codex-r2 (User-Entscheidung 2026-06-01): incident_id ist GLOBAL
            -- eindeutig (kein Projekt-Segment, keine per-project-Nummerierung).
            -- PK = incident_id allein; project_key bleibt NOT-NULL-Spalte und
            -- read/purge filtern weiterhin zwingend nach project_key (r1-Fix).
            -- Die FC-YYYY-NNNN-Nummern stammen aus einem globalen Per-Jahr-
            -- Zaehler (fc_incident_counters, gekeyt auf year allein).
            -- incident_id == FC-YYYY-NNNN (NNNN >= 4 Stellen, NUR Ziffern). Der
            -- Prefix-GLOB erzwingt FC-YYYY- + >=4 Ziffern; das NOT GLOB auf der
            -- Sequenz (ab Pos. 9) verbietet ein Nicht-Ziffern-Suffix wie
            -- "...0001x". Spiegelt den Pydantic-Validator (Jahr 4-stellig,
            -- Sequenz mindestens 4 Ziffern, nur Ziffern).
            CONSTRAINT fc_incidents_id_format
                CHECK (incident_id GLOB
                       'FC-[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]*'
                       AND substr(incident_id, 9) NOT GLOB '*[^0-9]*'),
            -- evidence_json = JSON-Array. Der Array-Typ wird per CHECK erzwungen;
            -- der Element-Typ (list[str], FK-41 §41.4.1) DB-seitig per
            -- BEFORE-Trigger (json_each, siehe unten) — ein CHECK kann JSON-Arrays
            -- nicht elementweise pruefen. Damit ist die DB symmetrisch zum
            -- Postgres-jsonpath-CHECK fail-closed (auch gegen Direktinserts).
            CONSTRAINT fc_incidents_evidence_is_array
                CHECK (json_valid(evidence_json)
                       AND json_type(evidence_json) = 'array'),
            -- tags ist optional; wenn gesetzt ein JSON-Array (Element-Typ
            -- list[str] erzwingt der BEFORE-Trigger unten). NULL erlaubt. Ohne
            -- diesen CHECK wuerde json_each einen Scalar/Objekt faelschlich als
            -- text-Rows durchwinken (Codex-r6).
            CONSTRAINT fc_incidents_tags_is_array
                CHECK (tags IS NULL
                       OR (json_valid(tags) AND json_type(tags) = 'array')),
            PRIMARY KEY (incident_id)
        );

        CREATE INDEX IF NOT EXISTS idx_fc_incidents_project_story_run
            ON fc_incidents (project_key, story_id, run_id);

        CREATE INDEX IF NOT EXISTS idx_fc_incidents_incident_status
            ON fc_incidents (incident_status);

        -- AG3-028 (Codex-r5): evidence_json/tags MUESSEN JSON-Arrays AUS STRINGS
        -- sein (FK-41 §41.4.1 list[str]). Ein CHECK kann Array-Elemente nicht
        -- iterieren; ein BEFORE-Trigger mit json_each schon. RAISE(ABORT) macht
        -- den Insert/Update fail-closed bei einem Nicht-String-Element — DB-Ebene,
        -- unabhaengig von Pydantic (deckt Direktinserts ab; symmetrisch zum
        -- Postgres-jsonpath-CHECK).
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

        -- AG3-028 (Codex-r2): GLOBALER Per-Jahr-Zaehler fuer die global
        -- eindeutige FC-YYYY-NNNN-Allokation (PK = year allein, KEIN
        -- project_key). Race-sicher in EINEM atomaren UPSERT mit RETURNING
        -- (SQLite >= 3.35), unter BEGIN IMMEDIATE serialisiert.
        CREATE TABLE IF NOT EXISTS fc_incident_counters (
            year              INTEGER NOT NULL,
            next_seq          INTEGER NOT NULL,
            PRIMARY KEY (year)
        );

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
        -- Schema-Owner agent-skills (SkillBinding entity, AG3-027); DB-Owner
        -- state_backend. Postgres ist kanonisch, dieses SQLite-Schema ist der
        -- Test-Parallel-Pfad mit IDENTISCHER DDL (symmetrisch zu
        -- postgres_schema.sql). Spalten spiegeln EXAKT das SkillBinding-Modell
        -- (kein manifest_digest, das Modell ist Owner der Shape). Upsert auf
        -- (project_key, skill_name). status deckt ALLE SECHS
        -- SkillLifecycleStatus-Werte ab (FAIL-CLOSED CHECK).
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
        -- Test-Parallel-Pfad mit IDENTISCHER DDL zu postgres_schema.sql (Postgres
        -- ist kanonisch). Kanonische (Wahrheits-)Seite der dualen Conflict-Freeze-
        -- Materialisierung; die lokale .agentkit/governance/freeze.json ist der
        -- hook-schnelle Export mit identischem freeze_version. Genau ein aktiver
        -- Freeze pro Story (PK story_id).
        CREATE TABLE IF NOT EXISTS governance_freeze_records (
            story_id        TEXT NOT NULL,
            frozen_at       TEXT NOT NULL,
            freeze_reason   TEXT NOT NULL,
            freeze_version  INTEGER NOT NULL,
            PRIMARY KEY (story_id)
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
        -- Test-Parallel-Pfad mit IDENTISCHER DDL zu postgres_schema.sql (Postgres
        -- ist kanonisch). Projektweiter Mode-Lock fuer die Fast/Standard-Mutual-
        -- Exclusion; AG3-034 stellt NUR den Read-Pfad fuer Preflight-Check 10 her
        -- (atomare Setzung = AG3-018-Folge, story.md §2.1.2 / §2.2). active_mode
        -- liegt auf der entkoppelten fast/standard-mode-Achse (WireStoryMode,
        -- FK-24 §24.3.3), NICHT auf der execution_route-Achse. NULL = idle.
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

        -- AG3-039 (FK-50 §50.3 CP 7, formal.installer.entities
        -- §project-registration): project_registry. Test-Parallel-Pfad zu
        -- postgres_schema.sql (Postgres ist kanonisch).
        -- Kanonische State-Backend-Registrierung fuer Installer-Checkpoint 7.
        -- project_root ist UNIQUE (genau eine Registrierung pro Filesystem-Root);
        -- runtime_profile ist auf die RuntimeProfile-Wire-Werte (core | are)
        -- eingeschraenkt. last_verified_at / last_upgraded_at bleiben NULL bis
        -- verify-project / ein Upgrade-Rerun sie setzen. Die Zeit-Spalten sind
        -- ISO-8601 TEXT, konsistent zur SQLite-Timestamp-Konvention der anderen
        -- AK3-Tabellen (SQLite hat keine native timestamptz-Affinitaet); der
        -- kanonische Postgres-Pfad nutzt dagegen TIMESTAMPTZ (story §2.1.1). Der
        -- Mapper roundtrippt datetime gegen beide Backends.
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
    the threshold. Pure structural split — identische DDL, idempotenter
    ``executescript``-Aufruf. Test-Parallel-Pfad zu ``postgres_schema.sql``
    (Postgres ist kanonisch; FK-41 §41.3.2/§41.3.3, FK-69 §69.3).
    """
    conn.executescript(
        """
        -- AG3-040 Sub-Block (b) (FK-41 §41.3.2, FK-69 §69.3): fc_patterns.
        -- Schema-Owner failure-corpus. Test-Parallel-Pfad mit IDENTISCHER
        -- Semantik zu postgres_schema.sql (Postgres ist kanonisch). status =
        -- pattern-status (4 Werte), category = FailureCategory (12 Werte),
        -- promotion_rule/risk_level mit den FK-41-Enums. incident_refs = JSON-
        -- Array von incident_id-Strings (Element-Typ list[str] via BEFORE-Trigger,
        -- da ein CHECK Array-Elemente nicht iterieren kann). NUR Tabelle +
        -- Repository-Skelett; Writer (PatternPromotion) ist Out of Scope.
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
                'wiederholung', 'hohe_schwere', 'checkbarkeit'
            )),
            risk_level        TEXT NOT NULL CHECK (risk_level IN (
                'mittel', 'hoch', 'kritisch'
            )),
            incident_count    INTEGER NOT NULL,
            confirmed_at      TEXT,
            confirmed_by      TEXT CHECK (confirmed_by IS NULL OR confirmed_by = 'human'),
            owner             TEXT,
            -- check_ref ist FK auf fc_check_proposals(check_id) (FK-41 §41.3.2:234).
            -- Zirkulaere FK mit fc_check_proposals.pattern_ref: SQLite erlaubt die
            -- Forward-Referenz in CREATE TABLE (FK-Ziel wird erst bei Benutzung
            -- aufgeloest), und _connect setzt PRAGMA foreign_keys = ON (erzwingt
            -- die FK identisch zu pattern_ref). Beide Refs sind nullable.
            check_ref         TEXT REFERENCES fc_check_proposals(check_id),
            retired_at        TEXT,
            -- pattern_id == FP-NNNN (NNNN >= 4 Stellen, NUR Ziffern). Der
            -- Prefix-GLOB erzwingt FP- + >=4 Ziffern; das NOT GLOB ab Pos. 4
            -- verbietet ein Nicht-Ziffern-Suffix.
            CONSTRAINT fc_patterns_id_format
                CHECK (pattern_id GLOB 'FP-[0-9][0-9][0-9][0-9]*'
                       AND substr(pattern_id, 4) NOT GLOB '*[^0-9]*'),
            -- incident_refs = JSON-Array (Array-Typ per CHECK; Element-Typ
            -- list[str] erzwingt der BEFORE-Trigger unten).
            CONSTRAINT fc_patterns_incident_refs_is_array
                CHECK (json_valid(incident_refs)
                       AND json_type(incident_refs) = 'array'),
            -- FK-41 §41.3.2:239: kein Pattern wechselt in 'accepted' ohne
            -- confirmed_by = 'human' (FAIL-CLOSED, Lifecycle-Invariante;
            -- spiegelt Postgres fc_patterns_accepted_human + Pydantic-Validator).
            CONSTRAINT fc_patterns_accepted_human
                CHECK (status <> 'accepted' OR confirmed_by IS 'human'),
            PRIMARY KEY (pattern_id)
        );

        CREATE INDEX IF NOT EXISTS idx_fc_patterns_project
            ON fc_patterns (project_key);

        CREATE INDEX IF NOT EXISTS idx_fc_patterns_status
            ON fc_patterns (status);

        -- incident_refs MUSS ein JSON-Array AUS STRINGS sein (FK-41 §41.3.2).
        -- Symmetrisch zum Postgres-jsonpath-CHECK + fc_incidents-Trigger.
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
        -- Schema-Owner failure-corpus. Test-Parallel-Pfad mit IDENTISCHER
        -- Semantik zu postgres_schema.sql. status = check-status (5 Werte),
        -- check_type = 6 FK-41-Werte, false_positive_risk = niedrig|mittel|hoch.
        -- pattern_ref ist FK auf fc_patterns(pattern_id). positive_/negative_
        -- fixtures = JSON-Arrays. NUR Tabelle + Repository-Skelett; Writer
        -- (CheckFactory) ist Out of Scope.
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
                'niedrig', 'mittel', 'hoch'
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
            -- check_id == CHK-NNNN (NNNN >= 4 Stellen, NUR Ziffern).
            CONSTRAINT fc_check_proposals_id_format
                CHECK (check_id GLOB 'CHK-[0-9][0-9][0-9][0-9]*'
                       AND substr(check_id, 5) NOT GLOB '*[^0-9]*'),
            -- positive_/negative_fixtures = JSON-Array (Array-Typ per CHECK;
            -- Element-Shape {description, expected} erzwingt der BEFORE-Trigger
            -- unten, da ein CHECK Array-Elemente nicht iterieren kann).
            CONSTRAINT fc_check_proposals_positive_fixtures_is_array
                CHECK (json_valid(positive_fixtures)
                       AND json_type(positive_fixtures) = 'array'),
            CONSTRAINT fc_check_proposals_negative_fixtures_is_array
                CHECK (json_valid(negative_fixtures)
                       AND json_type(negative_fixtures) = 'array'),
            -- FK-41 §41.3.3:282: approved_by muss 'human' sein; 'active' erbt die
            -- Pflicht (Vorwaerts-Uebergang aus 'approved'). FAIL-CLOSED, spiegelt
            -- Postgres fc_check_proposals_approved_human + Pydantic-Validator.
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

        -- positive_/negative_fixtures MUESSEN JSON-Arrays von {description,
        -- expected}-Objekten sein (FK-41 §41.3.3:265-266). Ein CHECK kann
        -- Array-Elemente nicht iterieren; ein BEFORE-Trigger mit json_each schon.
        -- RAISE(ABORT) macht Insert/Update fail-closed bei einem Element, das
        -- KEIN Objekt ist oder einen Pflicht-Key vermissen laesst. Damit kann die
        -- DB keinen fixtures-Wert halten, den der Repo-Decoder ablehnt
        -- (symmetrisch zum Postgres-jsonpath-CHECK *_fixtures_shape).
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
    from agentkit.state_backend.migration import MigrationRunner

    MigrationRunner().run(conn)


def _ensure_story_identity_migration(conn: sqlite3.Connection) -> None:
    """Apply idempotent story-identity schema migration.

    Rollback plan: drop ``story_contexts_story_uuid_idx``,
    ``story_contexts_project_story_number_idx`` and
    ``story_number_counters``; keep ``story_id`` and ``payload_json`` as the
    legacy source of truth. The migration only adds columns/indexes and
    backfills values from materialized ``story_id``.
    """

    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(story_contexts)").fetchall()
    }
    if "story_uuid" not in columns:
        conn.execute("ALTER TABLE story_contexts ADD COLUMN story_uuid TEXT")
    if "story_number" not in columns:
        conn.execute("ALTER TABLE story_contexts ADD COLUMN story_number INTEGER")

    for row in conn.execute(
        "SELECT project_key, story_id FROM story_contexts WHERE story_uuid IS NULL",
    ).fetchall():
        conn.execute(
            """
            UPDATE story_contexts
            SET story_uuid = ?
            WHERE project_key = ? AND story_id = ?
            """,
            (str(uuid4()), row["project_key"], row["story_id"]),
        )

    for row in conn.execute(
        "SELECT project_key, story_id FROM story_contexts WHERE story_number IS NULL",
    ).fetchall():
        story_number = _story_number_from_id(str(row["story_id"]))
        if story_number is None:
            continue
        conn.execute(
            """
            UPDATE story_contexts
            SET story_number = ?
            WHERE project_key = ? AND story_id = ?
            """,
            (story_number, row["project_key"], row["story_id"]),
        )

    _ensure_default_projects_for_story_contexts(conn)
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_story_uuid_idx
            ON story_contexts (story_uuid)
        """,
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_project_story_number_idx
            ON story_contexts (project_key, story_number)
        """,
    )
    conn.execute(
        """
        INSERT INTO story_number_counters (project_key, next_story_number)
        SELECT project_key, COALESCE(MAX(story_number), 0) + 1
        FROM story_contexts
        WHERE story_number IS NOT NULL
        GROUP BY project_key
        ON CONFLICT(project_key) DO UPDATE SET
            next_story_number = MAX(
                story_number_counters.next_story_number,
                excluded.next_story_number
            )
        """,
    )


def _ensure_four_phase_migration(conn: sqlite3.Connection) -> None:
    """Map legacy top-level verify phase records into implementation.

    Idempotent migration for the four-phase model. Existing implementation
    records win on key collisions; duplicate legacy verify records are removed
    after the safe update path. Rollback plan: restore from backup or rename
    affected implementation rows back to verify before starting a four-phase
    runtime.
    """

    conn.execute(
        """
        UPDATE phase_states
        SET phase = 'implementation'
        WHERE phase = 'verify'
        """,
    )
    conn.execute(
        """
        UPDATE flow_executions
        SET current_node_id = 'implementation'
        WHERE current_node_id = 'verify'
        """,
    )
    conn.execute(
        """
        UPDATE node_execution_ledgers
        SET node_id = 'implementation'
        WHERE node_id = 'verify'
          AND NOT EXISTS (
              SELECT 1 FROM node_execution_ledgers existing
              WHERE existing.story_id = node_execution_ledgers.story_id
                AND existing.flow_id = node_execution_ledgers.flow_id
                AND existing.node_id = 'implementation'
          )
        """,
    )
    conn.execute(
        """
        DELETE FROM node_execution_ledgers
        WHERE node_id = 'verify'
        """,
    )
    conn.execute(
        """
        UPDATE phase_snapshots
        SET phase = 'implementation'
        WHERE phase = 'verify'
          AND NOT EXISTS (
              SELECT 1 FROM phase_snapshots existing
              WHERE existing.story_id = phase_snapshots.story_id
                AND existing.phase = 'implementation'
          )
        """,
    )
    conn.execute(
        """
        DELETE FROM phase_snapshots
        WHERE phase = 'verify'
        """,
    )
    # Legacy ``attempt_records``-Tabelle ist mit Schema 3.5.0 entfernt
    # (siehe AG3-025 Re-Review-Befund 2): keine Migrations-Updates mehr
    # auf der Alt-Tabelle. ``attempts`` ist die neue Quelle und wird
    # nicht von der 'verify' -> 'implementation'-Konsolidierung beruehrt.


def _ensure_default_projects_for_story_contexts(conn: sqlite3.Connection) -> None:
    """Ensure every orphaned story_context has a parent project row.

    This migration-helper runs during schema bootstrap.  For each
    ``story_context`` that has no matching ``projects`` row, a minimal
    default project is inserted.

    The ``repositories`` field introduced by AG3-020 is derived from
    ``participating_repos`` in the story-context payload when available.
    When the payload carries no usable list, ``[project_key]`` is used as
    a last-resort placeholder so the strict ``ProjectConfiguration`` schema
    (``repositories: list[str] = Field(min_length=1)``) does not reject the
    row on read.  The mapper layer emits a WARN whenever this fallback is
    encountered so the operator can replace it.
    """
    import logging
    _log = logging.getLogger(__name__)

    rows = conn.execute(
        """
        SELECT DISTINCT sc.project_key, sc.story_id, sc.payload_json
        FROM story_contexts sc
        LEFT JOIN projects p ON p.key = sc.project_key
        WHERE p.key IS NULL
        """,
    ).fetchall()
    for row in rows:
        prefix = str(row["story_id"]).split("-", maxsplit=1)[0]
        project_key = str(row["project_key"])

        # Derive repositories from story-context payload when possible.
        repositories: list[str] = []
        try:
            import json as _json
            payload = _json.loads(str(row["payload_json"] or "{}"))
            participating = payload.get("participating_repos", [])
            if isinstance(participating, list) and participating:
                repositories = [str(r) for r in participating]
        except Exception:  # noqa: BLE001
            pass

        if not repositories:
            # Strict schema rejects []; fall back to [project_key] so the
            # default project is at least readable.  Mapper logs WARN.
            repositories = [project_key]
            _log.warning(
                "Bootstrap: project '%s' has no participating_repos in "
                "story_context payload; falling back to repositories=[%r] "
                "(operator MUST replace this placeholder).",
                project_key,
                project_key,
            )

        default_configuration = _dump_json(
            {
                "repo_url": "",
                "default_branch": "main",
                "are_url": None,
                "default_worker_count": 1,
                "repositories": repositories,
            },
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO projects (
                key,
                name,
                story_id_prefix,
                configuration_json,
                archived_at
            )
            VALUES (?, ?, ?, ?, NULL)
            """,
            (
                project_key,
                project_key,
                prefix,
                default_configuration,
            ),
        )


def _ensure_project_for_story_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
) -> None:
    """Ensure a project row exists for a story-context being saved.

    When a story-context references a ``project_key`` that has no matching
    project row, a minimal default project is inserted.  The
    ``repositories`` field is populated from ``row["participating_repos"]``
    when present, otherwise an empty list is stored and a WARNING is logged.

    Args:
        conn: Active SQLite connection with schema already applied.
        row: Story-context dict being saved (may contain ``participating_repos``).
    """
    import logging
    _log = logging.getLogger(__name__)

    story_id = str(row["story_id"])
    prefix = story_id.split("-", maxsplit=1)[0]
    project_key = str(row["project_key"])
    existing_project = conn.execute(
        "SELECT 1 FROM projects WHERE key = ?",
        (project_key,),
    ).fetchone()
    if existing_project is not None:
        return

    # Derive repositories from story row when possible.
    repositories: list[str] = []
    participating = row.get("participating_repos", [])
    if isinstance(participating, list) and participating:
        repositories = [str(r) for r in participating]
    else:
        _log.warning(
            "Bootstrap: project '%s' story '%s' has no participating_repos; "
            "setting repositories=[] (operator must update project configuration).",
            project_key,
            story_id,
        )

    default_configuration = _dump_json(
        {
            "repo_url": "",
            "default_branch": "main",
            "are_url": None,
            "default_worker_count": 1,
            "repositories": repositories,
        },
    )

    prefix_owner = conn.execute(
        "SELECT key FROM projects WHERE story_id_prefix = ?",
        (prefix,),
    ).fetchone()
    if prefix_owner is not None:
        prefix = _disambiguated_story_prefix(prefix, project_key)
    conn.execute(
        """
        INSERT OR IGNORE INTO projects (
            key,
            name,
            story_id_prefix,
            configuration_json,
            archived_at
        )
        VALUES (?, ?, ?, ?, NULL)
        """,
        (
            project_key,
            project_key,
            prefix,
            default_configuration,
        ),
    )


def _disambiguated_story_prefix(prefix: str, project_key: str) -> str:
    suffix = "".join(ch for ch in project_key.upper() if ch.isalnum())[:6]
    if not suffix:
        suffix = "X"
    return f"{prefix[: max(1, 10 - len(suffix))]}{suffix}"[:10]


def _story_number_from_id(story_id: str) -> int | None:
    suffix = story_id.rsplit("-", maxsplit=1)[-1]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _story_id_for(story_dir: Path) -> str | None:
    return story_dir.name or None


# ---------------------------------------------------------------------------
# StoryContext rows
# ---------------------------------------------------------------------------


def save_story_context_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a story-context row dict to the database and projection file."""

    payload_dict = json.loads(str(row["payload_json"]))
    with _connect(story_dir) as conn:
        _ensure_project_for_story_row(conn, row)
        conn.execute(
            """
            INSERT INTO story_contexts (
                story_uuid,
                project_key,
                story_number,
                story_id,
                story_type,
                execution_route,
                implementation_contract,
                issue_nr,
                title,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, story_id) DO UPDATE SET
                story_uuid=excluded.story_uuid,
                story_number=excluded.story_number,
                story_type=excluded.story_type,
                execution_route=excluded.execution_route,
                implementation_contract=excluded.implementation_contract,
                issue_nr=excluded.issue_nr,
                title=excluded.title,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                row["story_uuid"],
                row["project_key"],
                row["story_number"],
                row["story_id"],
                row["story_type"],
                row["execution_route"],
                row["implementation_contract"],
                row["issue_nr"],
                row["title"],
                row["payload_json"],
                now_iso(),
            ),
        )
    _write_projection(story_dir / CONTEXT_EXPORT_FILE, payload_dict)


def load_story_context_row(story_dir: Path) -> dict[str, Any] | None:
    """Return the raw payload row for a story context, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        rows = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise CorruptStateError(
            "story_contexts lookup is ambiguous without explicit project scope",
            detail={"story_dir": str(story_dir), "story_id": story_id},
        )
    return {"payload_json": str(rows[0]["payload_json"])}


def read_story_context_row(story_dir: Path) -> dict[str, Any] | None:
    """Canonical reader name for protected runtime modules."""

    return load_story_context_row(story_dir)


def save_story_context_global_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist a story-context row without requiring a story directory."""

    with _connect(_project_store_dir(store_dir)) as conn:
        _ensure_project_for_story_row(conn, row)
        conn.execute(
            """
            INSERT INTO story_contexts (
                story_uuid,
                project_key,
                story_number,
                story_id,
                story_type,
                execution_route,
                implementation_contract,
                issue_nr,
                title,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, story_id) DO UPDATE SET
                story_uuid=excluded.story_uuid,
                story_number=excluded.story_number,
                story_type=excluded.story_type,
                execution_route=excluded.execution_route,
                implementation_contract=excluded.implementation_contract,
                issue_nr=excluded.issue_nr,
                title=excluded.title,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                row["story_uuid"],
                row["project_key"],
                row["story_number"],
                row["story_id"],
                row["story_type"],
                row["execution_route"],
                row["implementation_contract"],
                row["issue_nr"],
                row["title"],
                row["payload_json"],
                now_iso(),
            ),
        )


def load_story_context_global_row(
    store_dir: Path | None,
    project_key: str,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the raw payload row for a global story context, or None."""

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE project_key = ? AND story_id = ?
            """,
            (project_key, story_id),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def load_story_context_rows_global(
    store_dir: Path | None,
    project_key: str,
) -> list[dict[str, Any]]:
    """Return all raw payload rows for a project's story contexts."""

    with _connect(_project_store_dir(store_dir)) as conn:
        rows = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE project_key = ?
            ORDER BY story_number ASC, story_id ASC
            """,
            (project_key,),
        ).fetchall()
    return [{"payload_json": str(row["payload_json"])} for row in rows]


def load_story_context_by_story_number_row(
    store_dir: Path | None,
    project_key: str,
    story_number: int,
) -> dict[str, Any] | None:
    """Return one story-context row by fachliche identity."""

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE project_key = ? AND story_number = ?
            """,
            (project_key, story_number),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def load_story_context_by_uuid_row(
    store_dir: Path | None,
    story_uuid: str,
) -> dict[str, Any] | None:
    """Return one story-context row by technical identity."""

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE story_uuid = ?
            """,
            (story_uuid,),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


# ---------------------------------------------------------------------------
# Execution planning rows
# ---------------------------------------------------------------------------


def save_story_dependency_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist one story dependency row.

    Migration note: ``story_dependencies`` is created idempotently by
    ``_ensure_schema``. Rollback is ``DROP TABLE story_dependencies`` plus its
    two indexes; no existing story-context data is mutated.
    """

    with _connect(_project_store_dir(store_dir)) as conn:
        conn.execute(
            """
            INSERT INTO story_dependencies (
                project_key,
                story_id,
                depends_on_story_id,
                kind,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                row["project_key"],
                row["story_id"],
                row["depends_on_story_id"],
                row["kind"],
                row["created_at"],
            ),
        )


def load_story_dependency_rows(
    store_dir: Path | None,
    project_key: str,
) -> list[dict[str, Any]]:
    """Load all dependency rows for one project."""

    with _connect(_project_store_dir(store_dir)) as conn:
        rows = conn.execute(
            """
            SELECT project_key, story_id, depends_on_story_id, kind, created_at
            FROM story_dependencies
            WHERE project_key = ?
            ORDER BY story_id, depends_on_story_id, kind
            """,
            (project_key,),
        ).fetchall()
    return [dict(row) for row in rows]


def load_story_dependency_rows_for_story(
    store_dir: Path | None,
    story_id: str,
) -> list[dict[str, Any]]:
    """Load direct predecessor dependency rows for one story."""

    with _connect(_project_store_dir(store_dir)) as conn:
        rows = conn.execute(
            """
            SELECT project_key, story_id, depends_on_story_id, kind, created_at
            FROM story_dependencies
            WHERE story_id = ?
            ORDER BY project_key, depends_on_story_id, kind
            """,
            (story_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_story_dependency_row(
    store_dir: Path | None,
    story_id: str,
    depends_on_story_id: str,
    kind: str,
) -> int:
    """Delete one dependency row and return affected row count."""

    with _connect(_project_store_dir(store_dir)) as conn:
        cursor = conn.execute(
            """
            DELETE FROM story_dependencies
            WHERE story_id = ? AND depends_on_story_id = ? AND kind = ?
            """,
            (story_id, depends_on_story_id, kind),
        )
        return cursor.rowcount


def save_parallelization_config_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist one parallelization config row."""

    with _connect(_project_store_dir(store_dir)) as conn:
        conn.execute(
            """
            INSERT INTO parallelization_configs (
                project_key,
                max_parallel_stories,
                max_parallel_stories_per_repo,
                extra_config_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_key) DO UPDATE SET
                max_parallel_stories = excluded.max_parallel_stories,
                max_parallel_stories_per_repo =
                    excluded.max_parallel_stories_per_repo,
                extra_config_json = excluded.extra_config_json,
                updated_at = excluded.updated_at
            """,
            (
                row["project_key"],
                row["max_parallel_stories"],
                row["max_parallel_stories_per_repo"],
                row["extra_config_json"],
                now_iso(),
            ),
        )


def load_parallelization_config_row(
    store_dir: Path | None,
    project_key: str,
) -> dict[str, Any] | None:
    """Load one parallelization config row."""

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT
                project_key,
                max_parallel_stories,
                max_parallel_stories_per_repo,
                extra_config_json
            FROM parallelization_configs
            WHERE project_key = ?
            """,
            (project_key,),
        ).fetchone()
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Requirements coverage rows
# ---------------------------------------------------------------------------


def save_story_are_link_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist one StoryAreLink row.

    Migration note: ``story_are_links`` is created idempotently by
    ``_ensure_schema``. Rollback is ``DROP TABLE story_are_links`` plus the
    optional ``story_contexts_story_id_idx`` index if no other table uses it;
    no existing StoryContext rows are mutated.
    """

    with _connect(_project_store_dir(store_dir)) as conn:
        conn.execute(
            """
            INSERT INTO story_are_links (
                story_id,
                are_item_id,
                kind
            ) VALUES (?, ?, ?)
            """,
            (
                row["story_id"],
                row["are_item_id"],
                row["kind"],
            ),
        )


def load_story_are_link_rows(
    store_dir: Path | None,
    story_id: str,
) -> list[dict[str, Any]]:
    """Load StoryAreLink rows for one story."""

    with _connect(_project_store_dir(store_dir)) as conn:
        rows = conn.execute(
            """
            SELECT story_id, are_item_id, kind
            FROM story_are_links
            WHERE story_id = ?
            ORDER BY are_item_id, kind
            """,
            (story_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_story_are_link_kind_row(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    old_kind: str,
    new_kind: str,
) -> dict[str, Any] | None:
    """Update one StoryAreLink kind and return the resulting row."""

    with _connect(_project_store_dir(store_dir)) as conn:
        cursor = conn.execute(
            """
            UPDATE story_are_links
            SET kind = ?
            WHERE story_id = ? AND are_item_id = ? AND kind = ?
            """,
            (new_kind, story_id, are_item_id, old_kind),
        )
        if cursor.rowcount == 0:
            return None
        row = conn.execute(
            """
            SELECT story_id, are_item_id, kind
            FROM story_are_links
            WHERE story_id = ? AND are_item_id = ? AND kind = ?
            """,
            (story_id, are_item_id, new_kind),
        ).fetchone()
    return dict(row) if row is not None else None


def delete_story_are_link_row(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    kind: str,
) -> int:
    """Delete one StoryAreLink row and return affected row count."""

    with _connect(_project_store_dir(store_dir)) as conn:
        cursor = conn.execute(
            """
            DELETE FROM story_are_links
            WHERE story_id = ? AND are_item_id = ? AND kind = ?
            """,
            (story_id, are_item_id, kind),
        )
        return cursor.rowcount


# ---------------------------------------------------------------------------
# Project rows
# ---------------------------------------------------------------------------


def _project_store_dir(store_dir: Path | None) -> Path:
    if store_dir is None:
        from pathlib import Path as _Path

        return _Path.cwd()
    return store_dir


def save_project_row(store_dir: Path | None, row: dict[str, Any]) -> None:
    """Persist a project row."""

    with _connect(_project_store_dir(store_dir)) as conn:
        conn.execute(
            """
            INSERT INTO projects (
                key,
                name,
                story_id_prefix,
                configuration_json,
                archived_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                name = excluded.name,
                configuration_json = excluded.configuration_json,
                archived_at = excluded.archived_at
            """,
            (
                row["key"],
                row["name"],
                row["story_id_prefix"],
                row["configuration_json"],
                row["archived_at"],
            ),
        )


def load_project_row(store_dir: Path | None, key: str) -> dict[str, Any] | None:
    """Load one project row by key."""

    with _connect(_project_store_dir(store_dir)) as conn:
        found = conn.execute(
            """
            SELECT
                key,
                name,
                story_id_prefix,
                configuration_json,
                archived_at
            FROM projects
            WHERE key = ?
            """,
            (key,),
        ).fetchone()
    return dict(found) if found is not None else None


def load_project_row_by_story_id_prefix(
    store_dir: Path | None,
    story_id_prefix: str,
) -> dict[str, Any] | None:
    """Load one project row by story-id prefix."""

    with _connect(_project_store_dir(store_dir)) as conn:
        found = conn.execute(
            """
            SELECT
                key,
                name,
                story_id_prefix,
                configuration_json,
                archived_at
            FROM projects
            WHERE story_id_prefix = ?
            """,
            (story_id_prefix,),
        ).fetchone()
    return dict(found) if found is not None else None


def load_project_rows(
    store_dir: Path | None,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Load project rows."""

    query = """
        SELECT
            key,
            name,
            story_id_prefix,
            configuration_json,
            archived_at
        FROM projects
        ORDER BY key
        """
    params: tuple[object, ...] = ()
    if not include_archived:
        query = """
            SELECT
                key,
                name,
                story_id_prefix,
                configuration_json,
                archived_at
            FROM projects
            WHERE archived_at IS NULL
            ORDER BY key
            """
    with _connect(_project_store_dir(store_dir)) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Project API token rows
# ---------------------------------------------------------------------------


def save_project_api_token_row(store_dir: Path | None, row: dict[str, Any]) -> None:
    """Persist a project API token row."""

    with _connect(_project_store_dir(store_dir)) as conn:
        conn.execute(
            """
            INSERT INTO project_api_tokens (
                token_id,
                project_key,
                label,
                token_hash,
                created_at,
                revoked_at,
                last_used_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(token_id) DO UPDATE SET
                label = excluded.label,
                token_hash = excluded.token_hash,
                revoked_at = excluded.revoked_at,
                last_used_at = excluded.last_used_at
            """,
            (
                row["token_id"],
                row["project_key"],
                row["label"],
                row["token_hash"],
                row["created_at"],
                row["revoked_at"],
                row["last_used_at"],
            ),
        )


def load_project_api_token_row(
    store_dir: Path | None,
    token_id: str,
) -> dict[str, Any] | None:
    """Load one project API token by id."""

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM project_api_tokens
            WHERE token_id = ?
            """,
            (token_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def load_project_api_token_row_by_hash(
    store_dir: Path | None,
    token_hash: str,
) -> dict[str, Any] | None:
    """Load one project API token by hash."""

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM project_api_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
    return dict(row) if row is not None else None


def load_project_api_token_rows_for_project(
    store_dir: Path | None,
    project_key: str,
) -> list[dict[str, Any]]:
    """Load project API tokens for one project."""

    with _connect(_project_store_dir(store_dir)) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM project_api_tokens
            WHERE project_key = ?
            ORDER BY created_at ASC, token_id ASC
            """,
            (project_key,),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# PhaseState rows
# ---------------------------------------------------------------------------


def save_phase_state_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a phase-state row dict to the database and projection file."""

    payload_dict = json.loads(str(row["payload_json"]))
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO phase_states (
                story_id, phase, status, paused_reason, review_round,
                attempt_id, errors_json, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                phase=excluded.phase,
                status=excluded.status,
                paused_reason=excluded.paused_reason,
                review_round=excluded.review_round,
                attempt_id=excluded.attempt_id,
                errors_json=excluded.errors_json,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                row["story_id"],
                row["phase"],
                row["status"],
                row["paused_reason"],
                row["review_round"],
                row["attempt_id"],
                row["errors_json"],
                row["payload_json"],
                now_iso(),
            ),
        )
    _write_projection(story_dir / PHASE_STATE_EXPORT_FILE, payload_dict)


def load_phase_state_row(story_dir: Path) -> dict[str, Any] | None:
    """Return the raw payload row for a phase state, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM phase_states
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def read_phase_state_row(story_dir: Path) -> dict[str, Any] | None:
    """Canonical reader name for protected runtime modules."""

    return load_phase_state_row(story_dir)


def load_phase_state_global_row(
    store_dir: Path | None,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the raw payload row for a global phase state, or None."""

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM phase_states
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


# ---------------------------------------------------------------------------
# PhaseSnapshot rows
# ---------------------------------------------------------------------------


def save_phase_snapshot_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a phase-snapshot row dict to the database and projection file."""

    payload_dict = json.loads(str(row["payload_json"]))
    phase = str(row["phase"])
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO phase_snapshots (
                story_id, phase, status, completed_at, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(story_id, phase) DO UPDATE SET
                status=excluded.status,
                completed_at=excluded.completed_at,
                payload_json=excluded.payload_json
            """,
            (
                row["story_id"],
                row["phase"],
                row["status"],
                row["completed_at"],
                row["payload_json"],
            ),
        )
    _write_projection(story_dir / f"phase-state-{phase}.json", payload_dict)


def load_phase_snapshot_row(story_dir: Path, phase: str) -> dict[str, Any] | None:
    """Return the raw payload row for a phase snapshot, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM phase_snapshots
            WHERE story_id = ? AND phase = ?
            """,
            (story_id, phase),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def read_phase_snapshot_row(story_dir: Path, phase: str) -> dict[str, Any] | None:
    """Canonical reader name for protected runtime modules."""

    return load_phase_snapshot_row(story_dir, phase)


# ---------------------------------------------------------------------------
# AttemptRecord rows
# ---------------------------------------------------------------------------


def save_attempt_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist an attempt row dict to the ``attempts`` table (Schema 3.5.0).

    ``story_id`` is derived from ``story_dir`` so AttemptRecords are
    story-scoped on persistence (FK-39 §39.4.1).  INSERT OR REPLACE makes
    a repeated call with the same PK idempotent.
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist attempt without story context in canonical backend",
        )
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO attempts (
                story_id, run_id, phase, attempt, outcome, failure_cause,
                started_at, ended_at, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story_id,
                row["run_id"],
                row["phase"],
                row["attempt"],
                row["outcome"],
                row.get("failure_cause"),
                row["started_at"],
                row["ended_at"],
                row.get("detail_json"),
            ),
        )


def load_attempt_rows(
    story_dir: Path,
    phase: str,
    *,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return attempt row dicts for a story+phase from the ``attempts`` table.

    Story-scoped: filters on ``story_id`` derived from ``story_dir``.
    When ``run_id`` is provided, additionally narrows to that run — used
    by ``EngineRuntimeState.generate_attempt_id`` to count attempts per
    run, not across runs.
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return []
    with _connect(story_dir) as conn:
        if run_id is None:
            rows = conn.execute(
                """
                SELECT * FROM attempts
                WHERE story_id = ? AND phase = ?
                ORDER BY attempt ASC
                """,
                (story_id, phase),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM attempts
                WHERE story_id = ? AND run_id = ? AND phase = ?
                ORDER BY attempt ASC
                """,
                (story_id, run_id, phase),
            ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# FlowExecution rows
# ---------------------------------------------------------------------------


def save_flow_execution_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a flow-execution row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO flow_executions (
                story_id, project_key, run_id, flow_id, level, owner,
                parent_flow_id, status, current_node_id, attempt_no,
                started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                project_key=excluded.project_key,
                run_id=excluded.run_id,
                flow_id=excluded.flow_id,
                level=excluded.level,
                owner=excluded.owner,
                parent_flow_id=excluded.parent_flow_id,
                status=excluded.status,
                current_node_id=excluded.current_node_id,
                attempt_no=excluded.attempt_no,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at
            """,
            (
                row["story_id"],
                row["project_key"],
                row["run_id"],
                row["flow_id"],
                row["level"],
                row["owner"],
                row["parent_flow_id"],
                row["status"],
                row["current_node_id"],
                row["attempt_no"],
                row["started_at"],
                row["finished_at"],
            ),
        )


def load_flow_execution_row(story_dir: Path) -> dict[str, Any] | None:
    """Return the raw flow-execution row, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT * FROM flow_executions
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# ExecutionEventRecord rows
# ---------------------------------------------------------------------------


def append_execution_event_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist an execution-event row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO execution_events (
                project_key, story_id, run_id, event_id, event_type,
                occurred_at, source_component, severity, phase, flow_id,
                node_id, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["event_id"],
                row["event_type"],
                row["occurred_at"],
                row["source_component"],
                row["severity"],
                row["phase"],
                row["flow_id"],
                row["node_id"],
                row["payload_json"],
            ),
        )


def append_execution_event_global_row(row: dict[str, Any]) -> None:
    """Global execution-event append is unsupported on SQLite."""

    del row
    raise RuntimeError(
        "Global execution-event append requires the postgres state backend",
    )


def load_execution_event_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return execution-event row dicts matching the given filters."""

    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append("project_key = ?")
        params.append(project_key)
    if story_id is not None:
        clauses.append("story_id = ?")
        params.append(story_id)
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT project_key, story_id, run_id, event_id, event_type,
                   occurred_at, source_component, severity, phase, flow_id,
                   node_id, payload_json
            FROM execution_events
            {where_clause}
            ORDER BY occurred_at ASC, event_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def load_execution_event_rows_for_project_global(
    project_key: str,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Global project execution-event reads are unsupported on SQLite."""

    del project_key, limit
    raise RuntimeError(
        "Global project execution-event reads require the postgres state backend",
    )


# ---------------------------------------------------------------------------
# StoryMetricsRecord rows
# ---------------------------------------------------------------------------


def upsert_story_metrics_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a story-metrics row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO story_metrics (
                project_key, story_id, run_id, story_type, story_size, mode,
                processing_time_min, qa_rounds, increments, final_status,
                completed_at, adversarial_findings, adversarial_tests_created,
                files_changed, agentkit_version, agentkit_commit,
                config_version, llm_roles_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, run_id) DO UPDATE SET
                story_id=excluded.story_id,
                story_type=excluded.story_type,
                story_size=excluded.story_size,
                mode=excluded.mode,
                processing_time_min=excluded.processing_time_min,
                qa_rounds=excluded.qa_rounds,
                increments=excluded.increments,
                final_status=excluded.final_status,
                completed_at=excluded.completed_at,
                adversarial_findings=excluded.adversarial_findings,
                adversarial_tests_created=excluded.adversarial_tests_created,
                files_changed=excluded.files_changed,
                agentkit_version=excluded.agentkit_version,
                agentkit_commit=excluded.agentkit_commit,
                config_version=excluded.config_version,
                llm_roles_json=excluded.llm_roles_json
            """,
            (
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["story_type"],
                row["story_size"],
                row["mode"],
                row["processing_time_min"],
                row["qa_rounds"],
                row["increments"],
                row["final_status"],
                row["completed_at"],
                row["adversarial_findings"],
                row["adversarial_tests_created"],
                row["files_changed"],
                row["agentkit_version"],
                row["agentkit_commit"],
                row["config_version"],
                row["llm_roles_json"],
            ),
        )


def load_story_metrics_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return story-metrics row dicts matching the given filters."""

    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append("project_key = ?")
        params.append(project_key)
    if story_id is not None:
        clauses.append("story_id = ?")
        params.append(story_id)
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM story_metrics
            {where_clause}
            ORDER BY completed_at ASC, run_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def load_latest_story_metrics_global_row(
    store_dir: Path | None,
    project_key: str,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the latest raw story-metrics row for a global lookup, or None."""

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM story_metrics
            WHERE project_key = ? AND story_id = ?
            ORDER BY completed_at DESC, run_id DESC
            LIMIT 1
            """,
            (project_key, story_id),
        ).fetchone()
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# NodeExecutionLedger rows
# ---------------------------------------------------------------------------


def save_node_execution_ledger_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a node-execution-ledger row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO node_execution_ledgers (
                story_id, flow_id, node_id, project_key, run_id,
                execution_count, success_count, last_outcome,
                last_attempt_no, last_executed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id, flow_id, node_id) DO UPDATE SET
                project_key=excluded.project_key,
                run_id=excluded.run_id,
                execution_count=excluded.execution_count,
                success_count=excluded.success_count,
                last_outcome=excluded.last_outcome,
                last_attempt_no=excluded.last_attempt_no,
                last_executed_at=excluded.last_executed_at
            """,
            (
                row["story_id"],
                row["flow_id"],
                row["node_id"],
                row["project_key"],
                row["run_id"],
                row["execution_count"],
                row["success_count"],
                row["last_outcome"],
                row["last_attempt_no"],
                row["last_executed_at"],
            ),
        )


def load_node_execution_ledger_row(
    story_dir: Path,
    flow_id: str,
    node_id: str,
) -> dict[str, Any] | None:
    """Return the raw node-execution-ledger row, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT * FROM node_execution_ledgers
            WHERE story_id = ? AND flow_id = ? AND node_id = ?
            """,
            (story_id, flow_id, node_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# OverrideRecord rows
# ---------------------------------------------------------------------------


def save_override_record_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist an override-record row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO override_records (
                override_id, story_id, project_key, run_id, flow_id,
                target_node_id, override_type, actor_type, actor_id,
                reason, created_at, consumed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(override_id) DO UPDATE SET
                target_node_id=excluded.target_node_id,
                override_type=excluded.override_type,
                actor_type=excluded.actor_type,
                actor_id=excluded.actor_id,
                reason=excluded.reason,
                created_at=excluded.created_at,
                consumed_at=excluded.consumed_at
            """,
            (
                row["override_id"],
                row["story_id"],
                row["project_key"],
                row["run_id"],
                row["flow_id"],
                row["target_node_id"],
                row["override_type"],
                row["actor_type"],
                row["actor_id"],
                row["reason"],
                row["created_at"],
                row["consumed_at"],
            ),
        )


def load_override_record_rows(story_dir: Path) -> list[dict[str, Any]]:
    """Return override-record row dicts for a story, ordered by created_at."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return []
    with _connect(story_dir) as conn:
        rows = conn.execute(
            """
            SELECT * FROM override_records
            WHERE story_id = ?
            ORDER BY created_at ASC
            """,
            (story_id,),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# QA layer artifacts + QA decision
# ---------------------------------------------------------------------------

def persist_layer_artifact_rows(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    layer_payload_rows: list[dict[str, object]],
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist QA layer artifact rows and write projection files.

    ``layer_payload_rows`` contains pre-serialized dicts from the mapper layer.
    Each element has keys: ``layer``, ``artifact_name``, ``producer_component``,
    ``payload``, ``passed``, ``recorded_at``.
    ``flow_row`` and FK-69 fields (``stage_row``, ``finding_rows``) are
    ignored on SQLite (FK-69 read models are Postgres-only).
    artifact_records removed in 3.4.0 — projection file is the only SQLite output.
    """
    del flow_row
    del attempt_nr
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist QA layer artifacts without story context "
            "in canonical backend",
        )
    produced: list[str] = []
    for item in layer_payload_rows:
        artifact_name = str(item["artifact_name"])
        payload = cast("_JsonRecord", item["payload"])
        target_dir = projection_dir or story_dir
        _write_projection(target_dir / artifact_name, payload)
        produced.append(artifact_name)
    return tuple(produced)


def persist_verify_decision_row(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    decision_row: dict[str, Any],
    canonical_payload: dict[str, object],
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist a verify-decision row and write the projection file."""

    del flow_row
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist verify decision without story context in canonical backend",
        )
    target_dir = projection_dir or story_dir
    _write_projection(target_dir / VERIFY_DECISION_FILE, canonical_payload)
    written = (VERIFY_DECISION_FILE,)
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO decision_records (
                story_id, decision_kind, attempt_nr, status, passed,
                summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id, decision_kind, attempt_nr) DO UPDATE SET
                status=excluded.status,
                passed=excluded.passed,
                summary=excluded.summary,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                story_id,
                "verify",
                attempt_nr,
                decision_row["status"],
                1 if decision_row["passed"] else 0,
                decision_row["summary"],
                _dump_json(canonical_payload),
                now_iso(),
            ),
        )
    return written


def load_latest_verify_decision_payload(
    story_dir: Path,
) -> dict[str, object] | None:
    """Return the latest verify-decision payload dict, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json
            FROM decision_records
            WHERE story_id = ? AND decision_kind = 'verify'
            ORDER BY attempt_nr DESC
            LIMIT 1
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    try:
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"decision_records payload is invalid in {state_db_path_for(story_dir)}: {exc}",
        ) from exc


def load_latest_verify_decision_payload_for_scope(
    scope: RuntimeStateScope,
) -> dict[str, object] | None:
    """Return the latest verify-decision payload for a scope, or None."""

    return load_latest_verify_decision_payload(scope.story_dir)


def load_artifact_record_payload(
    story_dir: Path,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Return the latest QA artifact payload from artifact_envelopes for a kind.

    Maps artifact_kind ("structural"/"semantic"/"adversarial") to stage
    "qa-layer-{kind}" and reads from artifact_envelopes (AG3-023 3.4.0).
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    stage = f"qa-layer-{artifact_kind}"
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json
            FROM artifact_envelopes
            WHERE story_id = ? AND stage = ?
            ORDER BY attempt DESC
            LIMIT 1
            """,
            (story_id, stage),
        ).fetchone()
    if row is None:
        return None
    raw = row["payload_json"]
    if raw is None:
        return None
    try:
        return _cast_json_record(json.loads(str(raw)))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"artifact_envelopes payload is invalid in {state_db_path_for(story_dir)}: {exc}",
        ) from exc


def load_artifact_record_payload_for_scope(
    scope: RuntimeStateScope,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Return the latest artifact payload dict for a scope and kind, or None."""

    return load_artifact_record_payload(scope.story_dir, artifact_kind)


def persist_closure_report_row(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    report_row: dict[str, Any],
    projection_dir: Path | None = None,
) -> Path:
    """Persist a closure-report and write the projection file."""

    del flow_row
    target_dir = projection_dir or story_dir
    path = target_dir / CLOSURE_REPORT_FILE
    payload = cast("_JsonRecord", report_row["payload"])
    _write_projection(path, payload)
    return path


# ---------------------------------------------------------------------------
# QA read models (SQLite: Postgres-only, raise RuntimeError)
# ---------------------------------------------------------------------------


def load_qa_stage_result_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[dict[str, Any]]:
    """FK-69 QA read models are only materialized on the Postgres backend."""

    del story_dir, project_key, story_id, run_id, attempt_no, stage_id
    raise RuntimeError(
        "FK-69 QA read models are only materialized on the Postgres backend. "
        "SQLite remains a narrow unit-test backend.",
    )


def load_qa_finding_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[dict[str, Any]]:
    """FK-69 QA read models are only materialized on the Postgres backend."""

    del story_dir, project_key, story_id, run_id, attempt_no, stage_id
    raise RuntimeError(
        "FK-69 QA read models are only materialized on the Postgres backend. "
        "SQLite remains a narrow unit-test backend.",
    )


# ---------------------------------------------------------------------------
# StoryExecutionLockRecord rows
# ---------------------------------------------------------------------------


def save_story_execution_lock_global_row(row: dict[str, Any]) -> None:
    """Persist a story-execution-lock row dict globally.

    AG3-031 Pass-7: SQLite path symmetric with postgres_store.
    Table DDL is bootstrapped via ``_ensure_schema_runtime_tables``.
    Uses ``_project_store_dir(None)`` (= ``Path.cwd()``) as the global
    store location, consistent with all other ``*_global_row`` functions.
    """

    with _connect(_project_store_dir(None)) as conn:
        conn.execute(
            """
            INSERT INTO story_execution_locks (
                project_key, story_id, run_id, lock_type, status,
                worktree_roots_json, binding_version, activated_at,
                updated_at, deactivated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (project_key, story_id, run_id, lock_type) DO UPDATE SET
                status = EXCLUDED.status,
                worktree_roots_json = EXCLUDED.worktree_roots_json,
                binding_version = EXCLUDED.binding_version,
                activated_at = EXCLUDED.activated_at,
                updated_at = EXCLUDED.updated_at,
                deactivated_at = EXCLUDED.deactivated_at
            """,
            (
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["lock_type"],
                row["status"],
                row["worktree_roots_json"],
                row["binding_version"],
                row["activated_at"],
                row["updated_at"],
                row["deactivated_at"],
            ),
        )


def load_story_execution_lock_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
    lock_type: str = "story_execution",
) -> dict[str, Any] | None:
    """Return the raw story-execution-lock row, or None.

    AG3-031 Pass-7: SQLite path symmetric with postgres_store.
    Uses ``_project_store_dir(None)`` (= ``Path.cwd()``) as the global
    store location.
    """

    with _connect(_project_store_dir(None)) as conn:
        row = conn.execute(
            """
            SELECT * FROM story_execution_locks
            WHERE project_key = ? AND story_id = ? AND run_id = ? AND lock_type = ?
            """,
            (project_key, story_id, run_id, lock_type),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# Backend predicate helpers (kept as thin wrappers for driver-level checks)
# ---------------------------------------------------------------------------


def backend_has_valid_context(story_dir: Path) -> bool:
    return load_story_context_row(story_dir) is not None


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return load_phase_state_row(story_dir) is not None
