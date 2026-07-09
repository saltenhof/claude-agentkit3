"""Postgres schema bootstrap, canaries, and idempotent DDL reconciliation."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.ownership import BINDING_VERSION_SQL_CHECK
from agentkit.backend.state_backend.config import (
    resolve_schema_name,
)
from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

if TYPE_CHECKING:
    from ._compat import _CompatConnection

_SCHEMA_ENSURE_LOCK = threading.Lock()
_SCHEMA_ENSURED_NAMES: set[str] = set()

def _schema_create_script() -> str:
    schema_path = Path(__file__).with_name("postgres_schema.sql")
    return schema_path.read_text(encoding="utf-8")


def _ensure_versioned_schema(conn: _CompatConnection) -> None:
    # SINGLE SOURCE OF TRUTH: schema bootstrap is owned by schema_bootstrap and
    # quoted via sql.Identifier; operate on the raw connection because the
    # sqlite-style _CompatConnection.execute only accepts ``str`` queries.
    ensure_versioned_schema(conn._conn)


def _ensure_schema_once(conn: _CompatConnection) -> None:
    """Run the heavy canonical DDL bootstrap once per process.

    Every connection still runs ``ensure_versioned_schema`` above so its
    ``search_path`` is correct. The table/index/ALTER bootstrap is idempotent
    but expensive on Postgres and must not run on every HTTP request.
    """
    schema_name = resolve_schema_name()
    if schema_name in _SCHEMA_ENSURED_NAMES:
        return
    with _SCHEMA_ENSURE_LOCK:
        if schema_name in _SCHEMA_ENSURED_NAMES:
            return
        if _schema_is_bootstrapped(conn):
            _SCHEMA_ENSURED_NAMES.add(schema_name)
            return
        _ensure_schema(conn)
        _SCHEMA_ENSURED_NAMES.add(schema_name)


def _reset_schema_bootstrap_cache_for_tests() -> None:
    """Clear the process-local Postgres schema-bootstrap cache."""

    with _SCHEMA_ENSURE_LOCK:
        _SCHEMA_ENSURED_NAMES.clear()


def _schema_is_bootstrapped(conn: _CompatConnection) -> bool:
    """Return whether the selected schema already carries the complete DDL."""
    required_tables = (
        "projects",
        "story_contexts",
        "decision_records",
        "phase_snapshots",
        "project_mode_lock",
        "qa_stage_results",
        # AG3-137 canary: a pre-AG3-137 schema lacks these tables, so it reports
        # "not bootstrapped" and re-runs the full _ensure_schema — which creates
        # the new session-ownership tables, applies the additive ALTERs and runs
        # the run-ownership backfill. Without this canary the DDL short-circuit
        # would skip the migration on an existing production DB. ALL four AG3-137
        # tables are checked (not just run_ownership_records) so a PARTIALLY
        # migrated DB (one table present, the rest missing — a failed rollout or
        # a manual repair) still fails closed and forces a full bootstrap
        # (Codex WARNING §6 / ZERO DEBT).
        "run_ownership_records",
        "object_mutation_claims",
        "takeover_transfer_records",
        "takeover_approvals",
        "backend_instance_identity",
        # AG3-143 canary: a pre-AG3-143 schema lacks this table, so it reports
        # "not bootstrapped" and re-runs the full _ensure_schema (which creates
        # execution_contract_digests via the idempotent CREATE TABLE IF NOT
        # EXISTS in postgres_schema.sql -- no additive ALTER/backfill needed,
        # the table is brand-new and forward-only).
        "execution_contract_digests",
        # AG3-147 canary: push freshness/backlog is Postgres-only and now also
        # carries the boundary correlation fields used by hard push barriers.
        "push_freshness_records",
        "push_barrier_verdicts",
        "ref_protection_degradation_findings",
        # AG3-145 canary: a pre-AG3-145 schema lacks the Edge-Command-Queue
        # table; brand-new and forward-only (mirrors the AG3-143 precedent
        # above -- no additive ALTER/backfill needed).
        "edge_command_records",
    )
    table_rows = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = ANY(%s)
        """,
        (list(required_tables),),
    ).fetchall()
    if {str(row["table_name"]) for row in table_rows} != set(required_tables):
        return False
    flow_id = conn.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'decision_records'
          AND column_name = 'flow_id'
        """,
    ).fetchone()
    if flow_id is None:
        return False
    if not _ag3_137_additive_columns_present(conn):
        return False
    if not _ag3_147_push_freshness_columns_present(conn):
        return False
    if not _ag3_137_binding_constraints_present(conn):
        return False
    if not _analytics_versions_are_recorded(conn):
        return False
    return _fact_tables_are_fk62_shaped(conn)


#: The AG3-137 additive columns on the two pre-existing control-plane tables. A
#: partially migrated DB (the new tables created but a table missing its additive
#: ALTER columns) must fail the bootstrap canary so the additive ALTERs re-run
#: (Codex WARNING §6). Kept in lock-step with _schema_alter_statements() and the
#: fresh CREATE TABLE columns in postgres_schema.sql.
_AG3_137_ADDITIVE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("session_run_bindings", "status"),
    ("session_run_bindings", "revocation_reason"),
    ("control_plane_operations", "operation_epoch"),
    ("control_plane_operations", "backend_instance_id"),
    ("control_plane_operations", "instance_incarnation"),
    ("control_plane_operations", "declared_serialization_scope"),
    ("control_plane_operations", "finalized_at"),
    # AG3-140 (unified idempotency contract): the body-hash column on the
    # inflight-operation-record. Listed here so a same-version DB that predates
    # AG3-140 fails the bootstrap canary and re-runs the additive ALTERs -- which
    # add ``request_body_hash`` AND relax ``story_id`` to nullable (both in
    # _schema_alter_statements). Column existence is the canary; the co-located
    # ``story_id`` DROP NOT NULL re-runs on the same forced bootstrap.
    ("control_plane_operations", "request_body_hash"),
)

_AG3_147_PUSH_FRESHNESS_COLUMNS: tuple[str, ...] = (
    "last_sync_point_id",
    "last_command_id",
)


def _ag3_147_push_freshness_columns_present(conn: _CompatConnection) -> bool:
    """Return whether AG3-147 boundary-correlation columns exist."""
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'push_freshness_records'
          AND column_name = ANY(%s)
        """,
        (list(_AG3_147_PUSH_FRESHNESS_COLUMNS),),
    ).fetchall()
    present = {str(row["column_name"]) for row in rows}
    return set(_AG3_147_PUSH_FRESHNESS_COLUMNS) <= present


def _ag3_137_additive_columns_present(conn: _CompatConnection) -> bool:
    """Return whether every AG3-137 additive column exists (partial-migration guard).

    Complements the table-level canary in :func:`_schema_is_bootstrapped`: the new
    AG3-137 tables can all be present while an additive column on an EXISTING
    control-plane table is still missing (a partial rollout). Checking the
    columns too forces a full bootstrap in that case rather than silently
    skipping the additive ALTERs (Codex WARNING §6, fail-closed).
    """
    tables = sorted({table for table, _ in _AG3_137_ADDITIVE_COLUMNS})
    rows = conn.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = ANY(%s)
        """,
        (tables,),
    ).fetchall()
    present = {(str(row["table_name"]), str(row["column_name"])) for row in rows}
    return set(_AG3_137_ADDITIVE_COLUMNS) <= present


#: The two AG3-137 remediation CHECK constraints on ``session_run_bindings``. A DB
#: already shaped by the r1 rollout (b2b3d0bd) carries the four AG3-137 tables and
#: the additive columns but NOT these named CHECKs: the additive ``status`` ALTER
#: adds its column WITHOUT a check, and ``binding_version`` stayed a bare
#: ``TEXT NOT NULL``. The table/column canary above would therefore report such a
#: DB as bootstrapped, short-circuiting ``_ensure_schema`` so the legacy
#: normalisation (``_ensure_run_ownership_backfill``) and the ``ADD CONSTRAINT``
#: step (``_ensure_session_binding_constraints``) never run on the exact
#: existing-schema state this remediation targets. Inspecting ``pg_constraint``
#: for BOTH names closes that gap: a missing constraint fails the canary, forces a
#: full bootstrap, and the existing DB ends up as hard as a fresh schema at the
#: persistence boundary (Codex ERROR §5a/§4, fail-closed).
_AG3_137_BINDING_CONSTRAINTS: tuple[str, ...] = (
    "session_run_bindings_status_check",
    "session_run_bindings_binding_version_check",
)


def _ag3_137_binding_constraints_present(conn: _CompatConnection) -> bool:
    """Return whether both AG3-137 session-binding CHECK constraints exist.

    Complements the table/column canary in :func:`_schema_is_bootstrapped`: a DB
    migrated by the r1 rollout (``b2b3d0bd``) has every AG3-137 table and additive
    column yet lacks these two named CHECK constraints, so without this probe it
    would report bootstrapped and skip the constraint + legacy-normalisation step.
    Reading ``pg_constraint`` (scoped to ``current_schema()``) forces a full
    bootstrap when either constraint is absent (Codex ERROR §5a, fail-closed).
    """
    rows = conn.execute(
        """
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = current_schema()
          AND c.conname = ANY(%s)
        """,
        (list(_AG3_137_BINDING_CONSTRAINTS),),
    ).fetchall()
    present = {str(row["conname"]) for row in rows}
    return set(_AG3_137_BINDING_CONSTRAINTS) <= present


def _analytics_versions_are_recorded(conn: _CompatConnection) -> bool:
    required_versions = {"3.4", "3.5", "3.6"}
    table_row = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = 'schema_versions'
        """,
    ).fetchone()
    if table_row is None:
        return False
    version_rows = conn.execute(
        """
        SELECT version
        FROM schema_versions
        WHERE version = ANY(%s)
        """,
        (list(required_versions),),
    ).fetchall()
    return {str(row["version"]) for row in version_rows} == required_versions


def _fact_tables_are_fk62_shaped(conn: _CompatConnection) -> bool:
    for table, expected_columns in _fact_fk62_column_sets().items():
        column_rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %s
            """,
            (table,),
        ).fetchall()
        if {str(row["column_name"]) for row in column_rows} != set(expected_columns):
            return False
    return True


def _schema_alter_statements() -> tuple[str, ...]:
    return (
        "ALTER TABLE story_contexts ADD COLUMN IF NOT EXISTS story_uuid UUID",
        "ALTER TABLE story_contexts ADD COLUMN IF NOT EXISTS story_number INTEGER",
        (
            "DO $$ "
            "DECLARE status_constraint text; "
            "BEGIN "
            "IF to_regclass('edge_command_records') IS NULL THEN RETURN; END IF; "
            "SELECT c.conname INTO status_constraint "
            "FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = current_schema() "
            "AND t.relname = 'edge_command_records' "
            "AND c.contype = 'c' "
            "AND position('status' in pg_get_constraintdef(c.oid)) > 0 "
            "LIMIT 1; "
            "IF status_constraint IS NOT NULL THEN "
            "EXECUTE 'ALTER TABLE edge_command_records DROP CONSTRAINT ' || quote_ident(status_constraint); "
            "END IF; "
            "ALTER TABLE edge_command_records "
            "ADD CONSTRAINT edge_command_records_status_check "
            "CHECK (status IN ('created', 'delivered', 'completed', 'failed', 'superseded')); "
            "EXCEPTION WHEN duplicate_object THEN NULL; "
            "END $$"
        ),
        (
            "DO $$ "
            "DECLARE boundary_constraint text; "
            "BEGIN "
            "IF to_regclass('push_barrier_verdicts') IS NULL THEN RETURN; END IF; "
            "SELECT c.conname INTO boundary_constraint "
            "FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = current_schema() "
            "AND t.relname = 'push_barrier_verdicts' "
            "AND c.contype = 'c' "
            "AND position('boundary_type' in pg_get_constraintdef(c.oid)) > 0 "
            "LIMIT 1; "
            "IF boundary_constraint IS NOT NULL THEN "
            "EXECUTE 'ALTER TABLE push_barrier_verdicts DROP CONSTRAINT ' || quote_ident(boundary_constraint); "
            "END IF; "
            "DELETE FROM push_barrier_verdicts WHERE boundary_type = 'pre_merge'; "
            "ALTER TABLE push_barrier_verdicts "
            "ADD CONSTRAINT push_barrier_verdicts_boundary_type_check "
            "CHECK (boundary_type IN ('phase_completion', 'qa_cycle_boundary', 'yield_point', 'closure_entry')); "
            "EXCEPTION WHEN duplicate_object THEN NULL; "
            "END $$"
        ),
        ("UPDATE story_contexts SET story_uuid = gen_random_uuid() WHERE story_uuid IS NULL"),
        (
            "UPDATE story_contexts SET story_number = "
            "substring(story_id from '-([0-9]+)$')::INTEGER "
            "WHERE story_number IS NULL AND story_id ~ '-[0-9]+$'"
        ),
        (
            # AG3-020: backfill default projects MUST include `repositories` so
            # the strict ProjectConfiguration schema accepts the row on read.
            # The repositories list defaults to [project_key] — a last-resort
            # placeholder that the operator MUST replace with the real list.
            # The mapper layer emits a WARN whenever this fallback is read,
            # so the placeholder cannot drift unnoticed.
            "INSERT INTO projects (key, name, story_id_prefix, configuration, "
            "archived_at) "
            "SELECT DISTINCT sc.project_key, sc.project_key, "
            "CASE WHEN EXISTS ("
            "SELECT 1 FROM projects p2 "
            "WHERE p2.story_id_prefix = split_part(sc.story_id, '-', 1) "
            "AND p2.key <> sc.project_key"
            ") THEN left(split_part(sc.story_id, '-', 1), 4) || "
            "upper(substr(md5(sc.project_key), 1, 6)) "
            "ELSE split_part(sc.story_id, '-', 1) END, "
            "jsonb_build_object("
            "'repo_url', '', "
            "'default_branch', 'main', "
            "'are_url', NULL, "
            "'default_worker_count', 1, "
            "'repositories', jsonb_build_array(sc.project_key)"
            "), NULL::TIMESTAMPTZ "
            "FROM story_contexts sc "
            "LEFT JOIN projects p ON p.key = sc.project_key "
            "WHERE p.key IS NULL "
            "ON CONFLICT(key) DO NOTHING"
        ),
        "ALTER TABLE story_contexts ALTER COLUMN story_uuid SET DEFAULT gen_random_uuid()",
        "ALTER TABLE story_contexts ALTER COLUMN story_uuid SET NOT NULL",
        "ALTER TABLE story_contexts ALTER COLUMN story_number SET NOT NULL",
        ("CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_story_uuid_idx ON story_contexts (story_uuid)"),
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_project_story_number_idx "
            "ON story_contexts (project_key, story_number)"
        ),
        ("CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_story_id_idx ON story_contexts (story_id)"),
        (
            "CREATE TABLE IF NOT EXISTS story_are_links ("
            "story_id TEXT NOT NULL, "
            "are_item_id TEXT NOT NULL, "
            "kind TEXT NOT NULL, "
            "PRIMARY KEY (story_id, are_item_id, kind), "
            "FOREIGN KEY (story_id) REFERENCES story_contexts(story_id)"
            ")"
        ),
        (
            "INSERT INTO story_number_counters (project_key, next_story_number) "
            "SELECT project_key, COALESCE(MAX(story_number), 0) + 1 "
            "FROM story_contexts GROUP BY project_key "
            "ON CONFLICT(project_key) DO UPDATE SET next_story_number = "
            "GREATEST(story_number_counters.next_story_number, "
            "excluded.next_story_number)"
        ),
        # AG3-031 Pass-5 FK-22 §22.7 corrective: PK corrected to 4-tuple
        # (project_key, story_id, run_id, lock_type).  Old PK omitted story_id.
        # Applied under SCHEMA_VERSION 3.6.0 as the old schema was never in production.
        ("ALTER TABLE story_execution_locks DROP CONSTRAINT IF EXISTS story_execution_locks_pkey"),
        (
            "ALTER TABLE story_execution_locks "
            "ADD CONSTRAINT story_execution_locks_pkey "
            "PRIMARY KEY (project_key, story_id, run_id, lock_type)"
        ),
        "ALTER TABLE decision_records ADD COLUMN IF NOT EXISTS project_key TEXT",
        "ALTER TABLE decision_records ADD COLUMN IF NOT EXISTS run_id TEXT",
        "ALTER TABLE decision_records ADD COLUMN IF NOT EXISTS flow_id TEXT",
        "UPDATE phase_states SET phase = 'implementation' WHERE phase = 'verify'",
        ("UPDATE flow_executions SET current_node_id = 'implementation' WHERE current_node_id = 'verify'"),
        (
            "UPDATE node_execution_ledgers n SET node_id = 'implementation' "
            "WHERE n.node_id = 'verify' AND NOT EXISTS ("
            "SELECT 1 FROM node_execution_ledgers existing "
            "WHERE existing.story_id = n.story_id "
            "AND existing.flow_id = n.flow_id "
            "AND existing.node_id = 'implementation')"
        ),
        "DELETE FROM node_execution_ledgers WHERE node_id = 'verify'",
        (
            "UPDATE phase_snapshots p SET phase = 'implementation' "
            "WHERE p.phase = 'verify' AND NOT EXISTS ("
            "SELECT 1 FROM phase_snapshots existing "
            "WHERE existing.story_id = p.story_id "
            "AND existing.phase = 'implementation')"
        ),
        "DELETE FROM phase_snapshots WHERE phase = 'verify'",
        # AG3-054 (SCHEMA_VERSION 3.20.0, FK-91 / FK-22 §22.9): the
        # owner-scoped claim. A fresh schema gets these from CREATE TABLE; an
        # existing same-version schema gets them idempotently here. TEXT (not
        # TIMESTAMPTZ) for claimed_at matches the table's other instants
        # (created_at/updated_at) so the ownership-scoped finalize/release CAS
        # (AG3-054 WARNING-4) exact-match roundtrips through plain ISO-8601 text.
        ("ALTER TABLE control_plane_operations ADD COLUMN IF NOT EXISTS claimed_by TEXT"),
        ("ALTER TABLE control_plane_operations ADD COLUMN IF NOT EXISTS claimed_at TEXT"),
        (
            "CREATE INDEX IF NOT EXISTS control_plane_operations_run_idx "
            "ON control_plane_operations (project_key, story_id, run_id)"
        ),
        # AG3-137 (Session-Ownership schema foundation, Postgres-only K5): the
        # new tables come from postgres_schema.sql CREATE TABLE IF NOT EXISTS; the
        # ADDITIVE columns on the two pre-existing control-plane tables are
        # applied idempotently here for an existing same-version schema. All are
        # nullable / DEFAULT so a DB pre-populated with legacy rows survives
        # losslessly (AK3/AK4).
        ("ALTER TABLE session_run_bindings ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'"),
        ("ALTER TABLE session_run_bindings ADD COLUMN IF NOT EXISTS revocation_reason TEXT"),
        ("ALTER TABLE control_plane_operations ADD COLUMN IF NOT EXISTS operation_epoch INTEGER"),
        ("ALTER TABLE control_plane_operations ADD COLUMN IF NOT EXISTS backend_instance_id TEXT"),
        ("ALTER TABLE control_plane_operations ADD COLUMN IF NOT EXISTS instance_incarnation INTEGER"),
        ("ALTER TABLE control_plane_operations ADD COLUMN IF NOT EXISTS declared_serialization_scope TEXT"),
        ("ALTER TABLE control_plane_operations ADD COLUMN IF NOT EXISTS finalized_at TEXT"),
        # AG3-140 (unified idempotency contract): the ``request_body_hash`` column
        # + the ``story_id`` NOT-NULL relaxation on the inflight-operation-record.
        # A fresh schema gets both from postgres_schema.sql CREATE TABLE; an
        # existing same-version schema gets them idempotently here. Additive /
        # lossless on a pre-populated DB (every existing row keeps its non-null
        # story_id; DROP NOT NULL on an already-nullable column is a no-op).
        ("ALTER TABLE control_plane_operations ADD COLUMN IF NOT EXISTS request_body_hash TEXT"),
        ("ALTER TABLE control_plane_operations ALTER COLUMN story_id DROP NOT NULL"),
        # AG3-147 remediation: hard push barriers require boundary-correlated
        # freshness, so existing push_freshness_records rows need producer
        # metadata columns. Nullable keeps the migration additive/lossless; rows
        # without a sync-point id simply cannot satisfy a correlated barrier.
        ("ALTER TABLE push_freshness_records ADD COLUMN IF NOT EXISTS last_sync_point_id TEXT"),
        ("ALTER TABLE push_freshness_records ADD COLUMN IF NOT EXISTS last_command_id TEXT"),
        # The legacy ``attempt_records`` table was removed with schema 3.5.0
        # (AG3-025 re-review finding 2). No more migration updates.
        # AG3-057: Trigger 3 input column for existing Postgres schemas that
        # pre-date the postgres_schema.sql addition.  Idempotent via IF NOT EXISTS.
        ("ALTER TABLE stories ADD COLUMN IF NOT EXISTS new_structures BOOLEAN NOT NULL DEFAULT FALSE"),
        # AG3-068: VectorDB-conflict producer flag column for existing Postgres
        # schemas that pre-date the postgres_schema.sql addition (FK-21 §21.12).
        # Idempotent via IF NOT EXISTS.
        ("ALTER TABLE stories ADD COLUMN IF NOT EXISTS vectordb_conflict_resolved BOOLEAN NOT NULL DEFAULT FALSE"),
        # AG3-072 (FK-54 §54.8.5): materialized split lineage columns for existing
        # Postgres schemas that pre-date the postgres_schema.sql addition.
        # Idempotent via IF NOT EXISTS.
        "ALTER TABLE stories ADD COLUMN IF NOT EXISTS split_from TEXT NULL",
        ("ALTER TABLE stories ADD COLUMN IF NOT EXISTS split_successors JSONB NOT NULL DEFAULT '[]'::jsonb"),
    )


def _ensure_reporting_indexes(conn: _CompatConnection) -> None:
    conn.execute("ALTER TABLE decision_records DROP CONSTRAINT IF EXISTS decision_records_pkey")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS decision_records_scope_identity_idx
        ON decision_records (project_key, run_id, decision_kind, attempt_nr)
        """
    )


def _ensure_story_identity_constraints(conn: _CompatConnection) -> None:
    """Apply idempotent story-identity constraints.

    Rollback plan: drop ``story_contexts_project_key_fkey``,
    ``story_contexts_story_uuid_idx``,
    ``story_contexts_project_story_number_idx`` and
    ``story_number_counters``. The migration leaves legacy ``story_id`` columns
    untouched and backfills ``story_number`` from their numeric suffix.
    """

    conn.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'story_contexts_project_key_fkey'
            ) THEN
                ALTER TABLE story_contexts
                ADD CONSTRAINT story_contexts_project_key_fkey
                FOREIGN KEY (project_key) REFERENCES projects(key);
            END IF;
        END
        $$;
        """,
    )


def _ensure_failure_corpus_constraints(conn: _CompatConnection) -> None:
    """Apply the idempotent circular FK between fc_patterns and fc_check_proposals.

    FK-41 §41.3.2:234 defines ``fc_patterns.check_ref`` as a reference to
    ``fc_check_proposals(check_id)``; FK-41 §41.3.3:256 defines
    ``fc_check_proposals.pattern_ref`` as a reference to ``fc_patterns(pattern_id)``.
    The latter is inline in ``CREATE TABLE`` (fc_patterns exists first); the former
    is a forward reference and is therefore added here, after both tables exist.
    Both refs are nullable. Idempotent via ``pg_constraint`` existence guard.

    The existence guard is scoped to ``current_schema()`` (join
    ``pg_constraint`` -> ``pg_class`` -> ``pg_namespace``): in a shared DB with
    several versioned/test schemas (``ak3_v*``, ``ak3test_*``) a same-named
    constraint in ANOTHER schema must not make a fresh schema skip the FK, which
    would leave FK-41 §41.3.2:234 unenforced there. ``search_path`` is set to the
    resolved schema first (see ``schema_bootstrap.ensure_versioned_schema`` /
    AG3-051 test isolation), so ``current_schema()`` is exactly that target
    schema and every schema lacking the FK gets it.

    Rollback plan: drop ``fc_patterns_check_ref_fkey``; ``check_ref`` stays a plain
    nullable TEXT column.
    """
    conn.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE c.conname = 'fc_patterns_check_ref_fkey'
                  AND n.nspname = current_schema()
            ) THEN
                ALTER TABLE fc_patterns
                ADD CONSTRAINT fc_patterns_check_ref_fkey
                FOREIGN KEY (check_ref) REFERENCES fc_check_proposals(check_id);
            END IF;
        END
        $$;
        """,
    )


def _ensure_schema(conn: _CompatConnection) -> None:
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (f"agentkit_postgres_schema_ddl:{resolve_schema_name()}",),
    )
    _reconcile_fact_tables_fk62(conn)
    conn.executescript(_schema_create_script())
    for statement in _schema_alter_statements():
        conn.execute(statement)
    _ensure_reporting_indexes(conn)
    _ensure_story_identity_constraints(conn)
    _ensure_failure_corpus_constraints(conn)
    _ensure_run_ownership_backfill(conn)
    _ensure_session_binding_constraints(conn)
    _ensure_analytics_migration(conn)


class RunOwnershipBackfillError(RuntimeError):
    """Fail-closed signal that the AG3-137 ownership backfill cannot proceed.

    Raised when a running run's owner cannot be derived deterministically (no
    active binding to derive an owner from) or when the existing data would
    violate ``at_most_one_active_ownership_per_story`` (two active bindings for
    the same ``(project_key, story_id)``). The backfill never guesses an owner
    (IMPL-007 / AK6): it reports the finding and blocks so an operator resolves
    it explicitly.
    """


def _ensure_run_ownership_backfill(conn: _CompatConnection) -> None:
    """Idempotently backfill ``run_ownership_records`` for running runs (IMPL-007).

    For every running run that already has an active session binding, materialise
    exactly one active ownership record (``ownership_epoch = 1``,
    ``acquired_via = 'setup'``, owner derived from the binding). Pre-existing
    bindings are lifted to the new ``status`` / ``binding_version`` format. The
    step is deterministic and idempotent: a second bootstrap creates no duplicate
    (the ``NOT EXISTS`` guard plus ``ON CONFLICT DO NOTHING``), and it never
    guesses an owner — an unownable running run or an ambiguous double-active
    binding raises :class:`RunOwnershipBackfillError` fail-closed.

    Runs on the versioned Postgres control-plane schema only; the tables are
    Postgres-only by design (K5). No data-discarding path.

    Raises:
        RunOwnershipBackfillError: On a running run without a derivable owner or
            an ambiguous double-active binding per story.
    """
    # 1. Lift pre-existing bindings to the new format (idempotent value
    #    normalisation, never data-discarding): legacy rows carry a random
    #    ``bind-<uuid4>`` binding_version and no status.
    conn.execute(
        "UPDATE session_run_bindings SET status = 'active' WHERE status IS NULL OR status = ''",
    )
    conn.execute(
        # Normalise every NON-canonical legacy value (random bind-<uuid4>, empty,
        # '0', leading-zero forms) to the initial version '1' so the canonical
        # value domain holds before the CHECK constraint is added in
        # _ensure_session_binding_constraints (Codex ERROR §4 follow-through). The
        # regex is single-sourced from ownership.BINDING_VERSION_SQL_CHECK (a
        # trusted module constant, not user input) so it cannot drift from the
        # CHECK the same bootstrap installs below (target-3 / SSOT).
        f"UPDATE session_run_bindings SET binding_version = '1' WHERE binding_version !~ '{BINDING_VERSION_SQL_CHECK}'",
    )

    # 2. Ambiguity guard: two active bindings for the same (project, story)
    #    cannot both become an active ownership record. Fail closed, never pick.
    ambiguous = conn.execute(
        "SELECT project_key, story_id, COUNT(*) AS n "
        "FROM session_run_bindings WHERE status = 'active' "
        "GROUP BY project_key, story_id HAVING COUNT(*) > 1",
    ).fetchall()
    if ambiguous:
        raise RunOwnershipBackfillError(
            "AG3-137 ownership backfill refused: ambiguous active bindings "
            "(more than one active session binding per (project_key, story_id)) "
            f"for {[_backfill_row_key(row) for row in ambiguous]}; ownership is "
            "not guessed (IMPL-007, fail-closed).",
        )

    # 3. Fail-closed finding: a running run (an ACTIVE story_execution lock) with
    #    NO active binding to derive an owner from and NO active ownership record
    #    already. Never guessed.
    orphans = conn.execute(
        "SELECT l.project_key, l.story_id, l.run_id "
        "FROM story_execution_locks l "
        "WHERE l.lock_type = 'story_execution' AND l.status = 'ACTIVE' "
        "AND NOT EXISTS (SELECT 1 FROM session_run_bindings b "
        "WHERE b.project_key = l.project_key AND b.story_id = l.story_id "
        "AND b.run_id = l.run_id AND b.status = 'active') "
        "AND NOT EXISTS (SELECT 1 FROM run_ownership_records r "
        "WHERE r.project_key = l.project_key AND r.story_id = l.story_id "
        "AND r.run_id = l.run_id AND r.status = 'active')",
    ).fetchall()
    if orphans:
        raise RunOwnershipBackfillError(
            "AG3-137 ownership backfill refused: running run(s) without a "
            "derivable owner (active story_execution lock, no active binding, no "
            f"active ownership record) for {[_backfill_row_key(row) for row in orphans]}; "
            "ownership is not guessed (IMPL-007, fail-closed).",
        )

    # 4. Backfill one active ownership record per active binding lacking one.
    #    Idempotent via NOT EXISTS + ON CONFLICT (identity) DO NOTHING.
    conn.execute(
        "INSERT INTO run_ownership_records ("
        "project_key, story_id, run_id, owner_session_id, ownership_epoch, "
        "status, acquired_via, acquired_at, audit_ref) "
        "SELECT b.project_key, b.story_id, b.run_id, b.session_id, 1, "
        "'active', 'setup', b.updated_at, 'backfill:AG3-137' "
        "FROM session_run_bindings b "
        "WHERE b.status = 'active' AND NOT EXISTS ("
        "SELECT 1 FROM run_ownership_records r "
        "WHERE r.project_key = b.project_key AND r.story_id = b.story_id "
        "AND r.run_id = b.run_id) "
        "ON CONFLICT (project_key, story_id, run_id) DO NOTHING",
    )


def _ensure_session_binding_constraints(conn: _CompatConnection) -> None:
    """Idempotently ensure the AG3-137 session-binding CHECK constraints.

    Applied AFTER :func:`_ensure_run_ownership_backfill` has normalised legacy
    ``binding_version`` / ``status`` values, so ``ADD CONSTRAINT`` never trips on
    pre-existing rows. This closes Codex WARNING §5a: the additive
    ``session_run_bindings.status`` ALTER adds the column WITHOUT a check, so an
    existing production DB would otherwise get a SOFTER value domain than a fresh
    schema. Both named constraints mirror the fresh CREATE TABLE (postgres_schema
    .sql) 1:1:

    * ``session_run_bindings_status_check``: ``status IN ('active','revoked')``.
    * ``session_run_bindings_binding_version_check``: canonical integer domain,
      the persistence-boundary mirror of ``ownership.is_canonical_binding_version``
      (Codex ERROR §4). The regex is interpolated from the single canonical source
      ``ownership.BINDING_VERSION_SQL_CHECK`` (a trusted module constant, not user
      input) so the ALTER CHECK cannot drift from the Python predicate (target-3 /
      SSOT). The static ``postgres_schema.sql`` fresh-schema CHECK cannot
      interpolate the constant; its parity is pinned by a contract test instead.

    Named + existence-guarded so a fresh schema (whose CREATE TABLE already
    created the SAME named constraints) is a no-op, and re-running the bootstrap
    never duplicates a constraint.
    """
    conn.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE c.conname = 'session_run_bindings_status_check'
                  AND n.nspname = current_schema()
            ) THEN
                ALTER TABLE session_run_bindings
                ADD CONSTRAINT session_run_bindings_status_check
                CHECK (status IN ('active', 'revoked'));
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE c.conname = 'session_run_bindings_binding_version_check'
                  AND n.nspname = current_schema()
            ) THEN
                ALTER TABLE session_run_bindings
                ADD CONSTRAINT session_run_bindings_binding_version_check
                CHECK (binding_version ~ '{BINDING_VERSION_SQL_CHECK}');
            END IF;
        END
        $$;
        """,
    )


def _backfill_row_key(row: object) -> tuple[object, ...]:
    """Render a backfill finding row (``dict_row`` mapping) as a stable key tuple."""
    if isinstance(row, Mapping):
        keys = ("project_key", "story_id", "run_id")
        return tuple(row[key] for key in keys if key in row)
    return (row,)


#: AG3-117 (FK-62 §62.2.1-62.2.5): the five recompute-disposable rollup tables.
_FACT_TABLE_NAMES: tuple[str, ...] = (
    "fact_story",
    "fact_guard_period",
    "fact_pool_period",
    "fact_pipeline_period",
    "fact_corpus_period",
)


def _fact_fk62_column_sets() -> dict[str, frozenset[str]]:
    """Return the FK-62 final column set per ``fact_*`` table.

    Parsed from ``postgres_schema.sql`` itself — the canonical Postgres DDL that
    :func:`_ensure_schema` is about to apply — so the reconciliation compares an
    existing table against the EXACT shape the schema script will (re)create. This
    keeps the FK-62 truth single-sourced WITHOUT crossing the StateBackendDrivers ->
    StateBackendRepository boundary (AC010) that a ``store._fact_sql`` import would.
    """
    script = _schema_create_script()
    return {table: _create_table_columns(script, table) for table in _FACT_TABLE_NAMES}


def _create_table_body(script: str, table: str) -> str:
    """Return the parenthesised body of a ``CREATE TABLE ... <table> ( ... )`` block.

    Brace-matched so nested parens (e.g. ``NUMERIC(10,2)``) don't end the body early.
    """
    marker = f"CREATE TABLE IF NOT EXISTS {table} ("
    start = script.find(marker)
    if start < 0:  # pragma: no cover - defensive: the schema always carries them
        raise RuntimeError(f"{table}: CREATE TABLE block not found in schema script")
    depth = 0
    body_start = start + len(marker)
    for i in range(start + len(marker) - 1, len(script)):
        char = script[i]
        if char == "(":
            depth += 1
            if depth == 1:
                body_start = i + 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return script[body_start:i]
    raise RuntimeError(f"{table}: unterminated CREATE TABLE block in schema script")  # pragma: no cover


def _create_table_columns(script: str, table: str) -> frozenset[str]:
    """Extract the column names of a ``CREATE TABLE ... <table> ( ... )`` block.

    Reads the first identifier of each definition line inside the parenthesised
    body, skipping table-level constraint clauses (PRIMARY KEY, ...).
    """
    columns: set[str] = set()
    for raw_line in _create_table_body(script, table).split("\n"):
        line = raw_line.strip().rstrip(",")
        if not line or line.startswith("--"):
            continue
        first = line.split()[0]
        if first.upper() in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
            continue
        columns.add(first)
    return frozenset(columns)


def _reconcile_fact_tables_fk62(conn: _CompatConnection) -> None:
    """Reconcile any pre-AG3-117 ``fact_*`` table to the FK-62 §62.2 column set.

    MECHANISM (AG3-117 Finding 1). ``postgres_schema.sql`` (run by
    :func:`_ensure_schema` right after this) is the canonical typed DDL builder and
    creates the five ``fact_*`` tables with ``CREATE TABLE IF NOT EXISTS``. Because
    ``_ensure_schema`` runs on EVERY connection (see :func:`_connect_global`), an
    UNCONDITIONAL ``DROP TABLE`` would discard the recompute-disposable rollups on
    every ordinary startup. The fact tables are recompute-disposable rollups
    (FK-60 §60 P3), so the safe reconciliation is a COLUMN-SET-CONDITIONAL drop:

    * fresh PG (table absent) -> no drop; the schema script creates the FK-62 table.
    * existing-OLD PG (column set differs from FK-62) -> ``DROP TABLE ... CASCADE``;
      the schema script then rebuilds the table on the FK-62 column set, and the
      ``closed_at``/``period_start`` indexes apply cleanly. The discarded rows are a
      derivable projection the RefreshWorker recomputes (FK-60 §60 P3) — not a data
      corpus to preserve.
    * already-FK-62 PG (column set matches) -> NO drop; the rollups survive every
      startup (no repeated wipe).

    Each table's reconciliation is ONE idempotent ``DO`` block executed via psycopg
    (which handles dollar-quoting natively); it is NOT placed in
    ``postgres_schema.sql`` because that file is split by :func:`iter_sql_statements`,
    which has no dollar-quote awareness and would mis-split a ``DO $$`` body.
    The DROP is restricted to exactly the five disposable ``fact_*`` rollup tables.
    """
    schema = resolve_schema_name()
    for table, fk62_columns in _fact_fk62_column_sets().items():
        column_csv = ",".join(sorted(fk62_columns))
        # A PL/pgSQL ``DO`` body cannot receive bind parameters (Postgres has no
        # placeholders inside a DO block), so the comparison values are inlined as
        # SAFELY-QUOTED SQL string literals. All three are internal, non-user
        # values: ``schema`` is the resolver-validated schema name, ``table`` is one
        # of the fixed five fact-table names, ``column_csv`` is built from the
        # ``_fact_sql`` column constants. ``_sql_text_literal`` doubles single
        # quotes (defence-in-depth). The lookup is scoped to the resolved schema so
        # a same-named table in another schema is never touched.
        conn.execute(
            "DO $$\n"
            "DECLARE\n"
            "    existing_columns text;\n"
            f"    expected_columns text := {_sql_text_literal(column_csv)};\n"
            "BEGIN\n"
            "    SELECT string_agg(column_name, ',' ORDER BY column_name)\n"
            "      INTO existing_columns\n"
            "      FROM information_schema.columns\n"
            f"     WHERE table_schema = {_sql_text_literal(schema)}\n"
            f"       AND table_name = {_sql_text_literal(table)};\n"
            "    IF existing_columns IS NOT NULL\n"
            "       AND existing_columns IS DISTINCT FROM expected_columns THEN\n"
            f"        DROP TABLE IF EXISTS {table} CASCADE;\n"
            "    END IF;\n"
            "END $$;",
        )


def _sql_text_literal(value: str) -> str:
    """Return ``value`` as a single-quoted SQL text literal (quotes doubled)."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _ensure_analytics_migration(conn: _CompatConnection) -> None:
    """Run the analytics MigrationRunner so it is wired in production (FK-62 §62.4).

    AG3-117: ``postgres_schema.sql`` (applied just above) is the canonical typed
    Postgres truth and already carries the five ``fact_*`` tables on the FK-62
    §62.2 final shape. The MigrationRunner runs afterwards purely to record the
    logical analytics versions (3.4 -> 3.5 -> 3.6, head ``3.6``) in the idempotent
    ``schema_versions`` cursor (FK-62 §62.4.3); its DDL is a no-op against the
    already-typed tables. To keep the historical v_3_4 / v_3_6 statements
    no-op-safe against the FK-62-shaped tables on Postgres (where v_3_4's
    ``completed_at`` index and v_3_6's ``DROP TABLE`` would otherwise conflict
    with / discard the canonical typed tables), the runner records the analytics
    versions WITHOUT replaying their DDL on this backend. A double run records
    nothing new (proven idempotent).
    """
    from agentkit.backend.state_backend.migration import MigrationRunner

    MigrationRunner().run(conn, replay_ddl=False)
