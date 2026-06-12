"""PostgreSQL-backed canonical runtime store with JSON projections.

This module is a T-bloodtype infrastructure driver.
It MUST NOT import BC-Records (A-bloodtype components).
All BC-Record <-> dict conversions live in
``agentkit.state_backend.store.mappers`` (boundary.state_backend_repository).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import psycopg
from psycopg.rows import dict_row

from agentkit.boundary.filesystem import atomic_write_json, load_json_object
from agentkit.boundary.shared.time import now_iso
from agentkit.core_types.qa_artifact_names import VERIFY_DECISION_FILE
from agentkit.exceptions import (
    ControlPlaneBindingCollisionError,
    ControlPlaneClaimCollisionError,
    CorruptStateError,
)
from agentkit.state_backend.config import (
    STATE_DATABASE_URL_ENV,
    load_state_backend_config,
    resolve_schema_name,
)
from agentkit.state_backend.paths import (
    CLOSURE_REPORT_FILE,
    CONTEXT_EXPORT_FILE,
    PHASE_STATE_EXPORT_FILE,
)
from agentkit.state_backend.schema_bootstrap import ensure_versioned_schema

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from agentkit.state_backend.scope import RuntimeStateScope


_PROJECT_KEY_FILTER = "project_key = ?"
_STORY_ID_FILTER = "story_id = ?"
_RUN_ID_FILTER = "run_id = ?"
_JsonRecord = dict[str, object]
_OptionalString = str | None


def _database_url() -> str:
    config = load_state_backend_config()
    if not config.database_url:
        raise RuntimeError(
            f"{STATE_DATABASE_URL_ENV} must be set when "
            "AGENTKIT_STATE_BACKEND=postgres",
        )
    return config.database_url


def _database_label() -> str:
    return STATE_DATABASE_URL_ENV


def current_schema_name() -> str:
    """Return the resolved PostgreSQL schema used by this driver.

    Delegates to :func:`resolve_schema_name` so the test override (AG3-051) is
    honored consistently with every other connection path. Production returns
    the versioned ``ak3_v<slug>`` unchanged.
    """

    return resolve_schema_name()


def _consume_sql_comment(script: str, i: int) -> int | None:
    """Return the index just after a ``--`` or ``/* */`` comment opened at ``i``.

    Returns ``None`` when no comment starts at ``i``. The comment text (which
    may itself contain ``;``) is consumed wholesale so it never triggers a
    statement split.

    Args:
        script: The full SQL script.
        i: Candidate comment-start index.

    Returns:
        Index after the comment, or ``None``.
    """
    two = script[i : i + 2]
    n = len(script)
    if two == "--":
        newline = script.find("\n", i)
        return n if newline == -1 else newline + 1
    if two == "/*":
        end = script.find("*/", i + 2)
        return n if end == -1 else end + 2
    return None


def _consume_sql_string(script: str, i: int, quote: str) -> int:
    """Return the index just after a quoted literal/identifier opened at ``i``.

    Handles doubled-quote escapes (``''`` / ``""``); an unterminated literal
    consumes the rest of the script.

    Args:
        script: The full SQL script.
        i: Index of the opening quote.
        quote: The quote character (``'`` or ``"``).

    Returns:
        Index after the closing quote (or end of script).
    """
    n = len(script)
    j = i + 1
    while j < n:
        if script[j] != quote:
            j += 1
        elif j + 1 < n and script[j + 1] == quote:  # doubled escape stays inside
            j += 2
        else:
            return j + 1
    return n


def iter_sql_statements(script: str) -> Iterator[str]:
    """Yield individual SQL statements from a multi-statement script.

    Splits on top-level ``;`` only, ignoring semicolons inside single-quoted
    string literals, double-quoted identifiers, ``--`` line comments or
    ``/* */`` block comments (the scanning of those spans is delegated to
    :func:`_consume_sql_comment` / :func:`_consume_sql_string`). psycopg's
    ``execute`` accepts a single statement at a time, so a naive
    ``str.split(";")`` mis-splits any script whose comment or literal contains a
    ``;`` (FIX THE MODEL: the AG3-031 governance hotfix added a ``--`` comment
    containing ``;``, which the naive splitter executed as the bogus statement
    ``a 3-tuple key collapsed``).

    Comment-only / whitespace-only fragments are skipped so psycopg never
    receives an empty query.

    Args:
        script: One or more ``;``-separated SQL statements.

    Yields:
        Each non-empty statement, stripped of surrounding whitespace, with its
        original comments and literals intact (psycopg ignores them).
    """
    buf: list[str] = []
    has_code = False
    i, n = 0, len(script)
    while i < n:
        comment_end = _consume_sql_comment(script, i)
        if comment_end is not None:
            buf.append(script[i:comment_end])
            i = comment_end
            continue
        ch = script[i]
        if ch in {"'", '"'}:
            end = _consume_sql_string(script, i, ch)
            buf.append(script[i:end])
            has_code = True
            i = end
            continue
        if ch == ";":
            if has_code:
                yield "".join(buf).strip()
            buf = []
            has_code = False
        else:
            has_code = has_code or not ch.isspace()
            buf.append(ch)
        i += 1
    if has_code:
        yield "".join(buf).strip()


class _CompatConnection:
    """Compatibility wrapper translating sqlite-style queries to psycopg."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def execute(
        self,
        query: str,
        params: Sequence[object] = (),
    ) -> psycopg.Cursor[dict[str, Any]]:
        normalized = query.replace("?", "%s")
        return self._conn.execute(normalized, params)

    def executescript(self, script: str) -> None:
        for statement in iter_sql_statements(script):
            self._conn.execute(statement)


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


def _cast_optional_str(value: object) -> _OptionalString:
    return cast("_OptionalString", value)


@contextmanager
def _connect_global() -> Iterator[_CompatConnection]:
    conn = psycopg.connect(
        _database_url(),
        row_factory=dict_row,
    )
    compat = _CompatConnection(conn)
    _ensure_versioned_schema(compat)
    _ensure_schema(compat)
    try:
        yield compat
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _connect(story_dir: Path) -> Iterator[_CompatConnection]:
    del story_dir
    with _connect_global() as compat:
        yield compat


def _schema_create_script() -> str:
    schema_path = Path(__file__).with_name("postgres_schema.sql")
    return schema_path.read_text(encoding="utf-8")


def _ensure_versioned_schema(conn: _CompatConnection) -> None:
    # SINGLE SOURCE OF TRUTH: schema bootstrap is owned by schema_bootstrap and
    # quoted via sql.Identifier; operate on the raw connection because the
    # sqlite-style _CompatConnection.execute only accepts ``str`` queries.
    ensure_versioned_schema(conn._conn)


def _schema_alter_statements() -> tuple[str, ...]:
    return (
        "ALTER TABLE story_contexts ADD COLUMN IF NOT EXISTS story_uuid UUID",
        "ALTER TABLE story_contexts ADD COLUMN IF NOT EXISTS story_number INTEGER",
        (
            "UPDATE story_contexts SET story_uuid = gen_random_uuid() "
            "WHERE story_uuid IS NULL"
        ),
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
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_story_uuid_idx "
            "ON story_contexts (story_uuid)"
        ),
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_project_story_number_idx "
            "ON story_contexts (project_key, story_number)"
        ),
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS story_contexts_story_id_idx "
            "ON story_contexts (story_id)"
        ),
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
        (
            "ALTER TABLE story_execution_locks "
            "DROP CONSTRAINT IF EXISTS story_execution_locks_pkey"
        ),
        (
            "ALTER TABLE story_execution_locks "
            "ADD CONSTRAINT story_execution_locks_pkey "
            "PRIMARY KEY (project_key, story_id, run_id, lock_type)"
        ),
        "ALTER TABLE decision_records ADD COLUMN IF NOT EXISTS project_key TEXT",
        "ALTER TABLE decision_records ADD COLUMN IF NOT EXISTS run_id TEXT",
        "ALTER TABLE decision_records ADD COLUMN IF NOT EXISTS flow_id TEXT",
        "UPDATE phase_states SET phase = 'implementation' WHERE phase = 'verify'",
        (
            "UPDATE flow_executions SET current_node_id = 'implementation' "
            "WHERE current_node_id = 'verify'"
        ),
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
        # AG3-054 (SCHEMA_VERSION 3.20.0, FK-91 / FK-22 §22.9): leased,
        # owner-scoped claim. A fresh schema gets these from CREATE TABLE; an
        # existing same-version schema gets them idempotently here. TEXT (not
        # TIMESTAMPTZ) for claimed_at matches the table's other instants
        # (created_at/updated_at) so the lease-expiry compare and the CAS
        # exact-match roundtrip through plain ISO-8601 text.
        (
            "ALTER TABLE control_plane_operations "
            "ADD COLUMN IF NOT EXISTS claimed_by TEXT"
        ),
        (
            "ALTER TABLE control_plane_operations "
            "ADD COLUMN IF NOT EXISTS claimed_at TEXT"
        ),
        (
            "CREATE INDEX IF NOT EXISTS control_plane_operations_run_idx "
            "ON control_plane_operations (project_key, story_id, run_id)"
        ),
        # The legacy ``attempt_records`` table was removed with schema 3.5.0
        # (AG3-025 re-review finding 2). No more migration updates.
        # AG3-057: Trigger 3 input column for existing Postgres schemas that
        # pre-date the postgres_schema.sql addition.  Idempotent via IF NOT EXISTS.
        (
            "ALTER TABLE stories "
            "ADD COLUMN IF NOT EXISTS new_structures BOOLEAN NOT NULL DEFAULT FALSE"
        ),
        # AG3-068: VectorDB-conflict producer flag column for existing Postgres
        # schemas that pre-date the postgres_schema.sql addition (FK-21 §21.12).
        # Idempotent via IF NOT EXISTS.
        (
            "ALTER TABLE stories ADD COLUMN IF NOT EXISTS "
            "vectordb_conflict_resolved BOOLEAN NOT NULL DEFAULT FALSE"
        ),
        # AG3-072 (FK-54 §54.8.5): materialized split lineage columns for existing
        # Postgres schemas that pre-date the postgres_schema.sql addition.
        # Idempotent via IF NOT EXISTS.
        "ALTER TABLE stories ADD COLUMN IF NOT EXISTS split_from TEXT NULL",
        (
            "ALTER TABLE stories ADD COLUMN IF NOT EXISTS "
            "split_successors JSONB NOT NULL DEFAULT '[]'::jsonb"
        ),
    )


def _ensure_reporting_indexes(conn: _CompatConnection) -> None:
    conn.execute(
        "ALTER TABLE decision_records DROP CONSTRAINT IF EXISTS decision_records_pkey"
    )
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
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('agentkit_postgres_schema_ddl'))")
    conn.executescript(_schema_create_script())
    for statement in _schema_alter_statements():
        conn.execute(statement)
    _ensure_reporting_indexes(conn)
    _ensure_story_identity_constraints(conn)
    _ensure_failure_corpus_constraints(conn)
    _ensure_analytics_migration(conn)


def _ensure_analytics_migration(conn: _CompatConnection) -> None:
    """Run the analytics MigrationRunner so it is wired in production (FK-62 §62.4).

    The canonical typed analytics DDL lives in ``postgres_schema.sql`` and is
    already applied above; the MigrationRunner records logical analytics version
    ``3.4`` in the idempotent ``schema_versions`` cursor (FK-62 §62.4.3). Its
    ``CREATE TABLE IF NOT EXISTS`` statements are no-ops here (the typed tables
    exist), so there is no second DDL truth — only the version cursor is written.
    A double run records nothing new (proven idempotent).
    """
    from agentkit.state_backend.migration import MigrationRunner

    MigrationRunner().run(conn)


def _story_id_for(story_dir: Path) -> str | None:
    story_id = story_dir.name
    return story_id or None


def _ensure_project_for_story_row(
    conn: _CompatConnection,
    row: dict[str, Any],
) -> None:
    story_id = str(row["story_id"])
    prefix = story_id.split("-", maxsplit=1)[0]
    project_key = str(row["project_key"])
    existing_project = conn.execute(
        "SELECT 1 FROM projects WHERE key = ?",
        (project_key,),
    ).fetchone()
    if existing_project is not None:
        return
    prefix_owner = conn.execute(
        "SELECT key FROM projects WHERE story_id_prefix = ?",
        (prefix,),
    ).fetchone()
    if prefix_owner is not None:
        prefix = _disambiguated_story_prefix(prefix, project_key)
    conn.execute(
        # AG3-020: the schema requires a non-empty `repositories` list, so the
        # backfill default uses [project_key] as a last-resort placeholder.
        # The mapper layer emits a WARN whenever this fallback is read.
        """
        INSERT INTO projects (
            key,
            name,
            story_id_prefix,
            configuration,
            archived_at
        )
        VALUES (
            ?,
            ?,
            ?,
            jsonb_build_object(
                'repo_url', '',
                'default_branch', 'main',
                'are_url', NULL,
                'default_worker_count', 1,
                'repositories', jsonb_build_array(?::text)
            ),
            NULL::TIMESTAMPTZ
        )
        ON CONFLICT(key) DO NOTHING
        """,
        (project_key, project_key, prefix, project_key),
    )


def _disambiguated_story_prefix(prefix: str, project_key: str) -> str:
    import hashlib

    suffix = hashlib.md5(project_key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{prefix[:4]}{suffix[:6]}".upper()


def _artifact_id_for(artifact_kind: str, attempt_no: int | None = None) -> str:
    if attempt_no is None:
        return artifact_kind.replace("_", "-")
    return f"{artifact_kind.replace('_', '-')}-attempt-{attempt_no}"


def _produced_in_phase_for(artifact_kind: str) -> str:
    if artifact_kind == "closure_report":
        return "closure"
    return "implementation"


def _producer_trust_for(producer_component: str) -> str:
    if producer_component in {"qa-semantic-review"}:
        return "verified_llm"
    if producer_component in {"qa-adversarial"}:
        return "agent"
    return "system"


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

    del store_dir
    with _connect_global() as conn:
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

    del store_dir
    with _connect_global() as conn:
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


def load_story_context_by_story_number_row(
    store_dir: Path | None,
    project_key: str,
    story_number: int,
) -> dict[str, Any] | None:
    """Return one story-context row by domain identity."""

    del store_dir
    with _connect_global() as conn:
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

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE story_uuid = ?::uuid
            """,
            (story_uuid,),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def load_story_context_rows_global(
    store_dir: Path | None,
    project_key: str,
) -> list[dict[str, Any]]:
    """Return all raw payload rows for a project's story contexts."""

    del store_dir
    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT payload_json FROM story_contexts
            WHERE project_key = ?
            ORDER BY story_number ASC, story_id ASC
            """,
            (project_key,),
        ).fetchall()
    return [{"payload_json": str(row["payload_json"])} for row in rows]


# ---------------------------------------------------------------------------
# Execution planning rows
# ---------------------------------------------------------------------------


def save_story_dependency_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist one story dependency row.

    Migration note: ``story_dependencies`` is created idempotently by
    ``_schema_create_script``. Rollback is ``DROP TABLE story_dependencies``
    after dropping dependent indexes; no existing story-context data is
    modified.
    """

    del store_dir
    with _connect_global() as conn:
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

    del store_dir
    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT project_key, story_id, depends_on_story_id, kind, created_at
            FROM story_dependencies
            WHERE project_key = ?
            ORDER BY story_id, depends_on_story_id, kind
            """,
            (project_key,),
        ).fetchall()
    return rows


def load_story_dependency_rows_for_story(
    store_dir: Path | None,
    story_id: str,
) -> list[dict[str, Any]]:
    """Load direct predecessor dependency rows for one story."""

    del store_dir
    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT project_key, story_id, depends_on_story_id, kind, created_at
            FROM story_dependencies
            WHERE story_id = ?
            ORDER BY project_key, depends_on_story_id, kind
            """,
            (story_id,),
        ).fetchall()
    return rows


def delete_story_dependency_row(
    store_dir: Path | None,
    story_id: str,
    depends_on_story_id: str,
    kind: str,
) -> int:
    """Delete one dependency row and return affected row count."""

    del store_dir
    with _connect_global() as conn:
        cursor = conn.execute(
            """
            DELETE FROM story_dependencies
            WHERE story_id = ? AND depends_on_story_id = ? AND kind = ?
            """,
            (story_id, depends_on_story_id, kind),
        )
        return int(cursor.rowcount)


def save_parallelization_config_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist one parallelization config row."""

    del store_dir
    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO parallelization_configs (
                project_key,
                max_parallel_stories,
                max_parallel_stories_per_repo,
                extra_config,
                updated_at
            ) VALUES (?, ?, ?, ?::jsonb, now())
            ON CONFLICT(project_key) DO UPDATE SET
                max_parallel_stories = excluded.max_parallel_stories,
                max_parallel_stories_per_repo =
                    excluded.max_parallel_stories_per_repo,
                extra_config = excluded.extra_config,
                updated_at = excluded.updated_at
            """,
            (
                row["project_key"],
                row["max_parallel_stories"],
                row["max_parallel_stories_per_repo"],
                row["extra_config_json"],
            ),
        )


def load_parallelization_config_row(
    store_dir: Path | None,
    project_key: str,
) -> dict[str, Any] | None:
    """Load one parallelization config row."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT
                project_key,
                max_parallel_stories,
                max_parallel_stories_per_repo,
                extra_config AS extra_config_json
            FROM parallelization_configs
            WHERE project_key = ?
            """,
            (project_key,),
        ).fetchone()
    return row


# ---------------------------------------------------------------------------
# Requirements coverage rows
# ---------------------------------------------------------------------------


def save_story_are_link_row(
    store_dir: Path | None,
    row: dict[str, Any],
) -> None:
    """Persist one StoryAreLink row.

    Migration note: ``story_are_links`` is created idempotently by
    ``_schema_create_script``. Rollback is ``DROP TABLE story_are_links`` plus
    ``DROP INDEX story_contexts_story_id_idx`` if no other table depends on it;
    no existing StoryContext rows are mutated.
    """

    del store_dir
    with _connect_global() as conn:
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

    del store_dir
    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT story_id, are_item_id, kind
            FROM story_are_links
            WHERE story_id = ?
            ORDER BY are_item_id, kind
            """,
            (story_id,),
        ).fetchall()
    return rows


def update_story_are_link_kind_row(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    old_kind: str,
    new_kind: str,
) -> dict[str, Any] | None:
    """Update one StoryAreLink kind and return the resulting row."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            UPDATE story_are_links
            SET kind = ?
            WHERE story_id = ? AND are_item_id = ? AND kind = ?
            RETURNING story_id, are_item_id, kind
            """,
            (new_kind, story_id, are_item_id, old_kind),
        ).fetchone()
    return row


def delete_story_are_link_row(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    kind: str,
) -> int:
    """Delete one StoryAreLink row and return affected row count."""

    del store_dir
    with _connect_global() as conn:
        cursor = conn.execute(
            """
            DELETE FROM story_are_links
            WHERE story_id = ? AND are_item_id = ? AND kind = ?
            """,
            (story_id, are_item_id, kind),
        )
        return int(cursor.rowcount)


# ---------------------------------------------------------------------------
# Project rows
# ---------------------------------------------------------------------------


def save_project_row(store_dir: Path | None, row: dict[str, Any]) -> None:
    """Persist a project row."""

    del store_dir
    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO projects (
                key,
                name,
                story_id_prefix,
                configuration,
                archived_at
            )
            VALUES (?, ?, ?, ?::jsonb, ?)
            ON CONFLICT(key) DO UPDATE SET
                name = excluded.name,
                configuration = excluded.configuration,
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

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT
                key,
                name,
                story_id_prefix,
                configuration AS configuration_json,
                archived_at
            FROM projects
            WHERE key = ?
            """,
            (key,),
        ).fetchone()
    return row


def load_project_row_by_story_id_prefix(
    store_dir: Path | None,
    story_id_prefix: str,
) -> dict[str, Any] | None:
    """Load one project row by story-id prefix."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT
                key,
                name,
                story_id_prefix,
                configuration AS configuration_json,
                archived_at
            FROM projects
            WHERE story_id_prefix = ?
            """,
            (story_id_prefix,),
        ).fetchone()
    return row


def load_project_rows(
    store_dir: Path | None,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Load project rows."""

    del store_dir
    query = """
        SELECT
            key,
            name,
            story_id_prefix,
            configuration AS configuration_json,
            archived_at
        FROM projects
        ORDER BY key
        """
    if not include_archived:
        query = """
            SELECT
                key,
                name,
                story_id_prefix,
                configuration AS configuration_json,
                archived_at
            FROM projects
            WHERE archived_at IS NULL
            ORDER BY key
            """
    with _connect_global() as conn:
        rows = conn.execute(query).fetchall()
    return rows


# ---------------------------------------------------------------------------
# Project API token rows
# ---------------------------------------------------------------------------


def save_project_api_token_row(store_dir: Path | None, row: dict[str, Any]) -> None:
    """Persist a project API token row."""

    del store_dir
    with _connect_global() as conn:
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

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM project_api_tokens
            WHERE token_id = ?
            """,
            (token_id,),
        ).fetchone()
    return row


def load_project_api_token_row_by_hash(
    store_dir: Path | None,
    token_hash: str,
) -> dict[str, Any] | None:
    """Load one project API token by hash."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM project_api_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
    return row


def load_project_api_token_rows_for_project(
    store_dir: Path | None,
    project_key: str,
) -> list[dict[str, Any]]:
    """Load project API tokens for one project."""

    del store_dir
    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM project_api_tokens
            WHERE project_key = ?
            ORDER BY created_at ASC, token_id ASC
            """,
            (project_key,),
        ).fetchall()
    return rows


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

    del store_dir
    with _connect_global() as conn:
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
    story-scoped on the persistence side (FK-39 §39.4.1).  Idempotent:
    ``INSERT ... ON CONFLICT DO UPDATE`` overwrites the row on a
    re-write with the same ``(story_id, run_id, phase, attempt)`` key.
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist attempt without story context in canonical backend",
        )
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO attempts (
                story_id, run_id, phase, attempt, outcome, failure_cause,
                started_at, ended_at, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (story_id, run_id, phase, attempt) DO UPDATE SET
                outcome=excluded.outcome,
                failure_cause=excluded.failure_cause,
                started_at=excluded.started_at,
                ended_at=excluded.ended_at,
                detail_json=excluded.detail_json
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
    """Return attempt row dicts for a story+phase from ``attempts``.

    Filters on ``story_id`` (derived from ``story_dir``) and ``phase``.
    An optional ``run_id`` additionally narrows to a single run — used by
    ``EngineRuntimeState.generate_attempt_id`` to count attempts per
    run and not across runs.
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


def load_flow_execution_global_row(
    project_key: str,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the raw flow-execution row for a global lookup, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM flow_executions
            WHERE project_key = ? AND story_id = ?
            """,
            (project_key, story_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# ExecutionEventRecord rows
# ---------------------------------------------------------------------------


def _insert_execution_event_row(
    conn: _CompatConnection,
    row: dict[str, Any],
) -> None:
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


def append_execution_event_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist an execution-event row dict to the database."""

    with _connect(story_dir) as conn:
        _insert_execution_event_row(conn, row)


def append_execution_event_global_row(row: dict[str, Any]) -> None:
    """Persist an execution-event row dict globally."""

    with _connect_global() as conn:
        _insert_execution_event_row(conn, row)


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
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
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


def load_execution_event_rows_global(
    project_key: str,
    story_id: str,
    *,
    run_id: str | None = None,
    event_type: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return execution-event row dicts for a global project/story query."""

    if limit is not None and limit <= 0:
        return []
    clauses = [_PROJECT_KEY_FILTER, _STORY_ID_FILTER]
    params: list[object] = [project_key, story_id]
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT ?"
        params.append(limit)
    where_clause = f"WHERE {' AND '.join(clauses)}"
    with _connect_global() as conn:
        rows = conn.execute(
            f"""
            SELECT project_key, story_id, run_id, event_id, event_type,
                   occurred_at, source_component, severity, phase, flow_id,
                   node_id, payload_json
            FROM execution_events
            {where_clause}
            ORDER BY occurred_at DESC, event_id DESC
            {limit_clause}
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def load_execution_event_rows_for_project_global(
    project_key: str,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return recent execution-event rows for one project."""

    if limit is not None and limit <= 0:
        return []
    params: list[object] = [project_key]
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT ?"
        params.append(limit)
    with _connect_global() as conn:
        rows = conn.execute(
            f"""
            SELECT project_key, story_id, run_id, event_id, event_type,
                   occurred_at, source_component, severity, phase, flow_id,
                   node_id, payload_json
            FROM execution_events
            WHERE project_key = ?
            ORDER BY occurred_at DESC, event_id DESC
            {limit_clause}
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


# ---------------------------------------------------------------------------
# SessionRunBindingRecord rows
# ---------------------------------------------------------------------------


def save_session_run_binding_global_row(row: dict[str, Any]) -> None:
    """Persist a session-run-binding row dict globally."""

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO session_run_bindings (
                session_id, project_key, story_id, run_id, principal_type,
                worktree_roots_json, binding_version, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE SET
                project_key = EXCLUDED.project_key,
                story_id = EXCLUDED.story_id,
                run_id = EXCLUDED.run_id,
                principal_type = EXCLUDED.principal_type,
                worktree_roots_json = EXCLUDED.worktree_roots_json,
                binding_version = EXCLUDED.binding_version,
                updated_at = EXCLUDED.updated_at
            """,
            (
                row["session_id"],
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["principal_type"],
                row["worktree_roots_json"],
                row["binding_version"],
                row["updated_at"],
            ),
        )


def load_session_run_binding_global_row(
    session_id: str,
) -> dict[str, Any] | None:
    """Return the raw session-run-binding row for a session, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM session_run_bindings
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def delete_session_run_binding_global(session_id: str) -> None:
    """Delete a session-run-binding globally."""

    with _connect_global() as conn:
        conn.execute(
            """
            DELETE FROM session_run_bindings
            WHERE session_id = ?
            """,
            (session_id,),
        )


# ---------------------------------------------------------------------------
# StoryExecutionLockRecord rows
# ---------------------------------------------------------------------------


def save_story_execution_lock_global_row(row: dict[str, Any]) -> None:
    """Persist a story-execution-lock row dict globally."""

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO story_execution_locks (
                project_key, story_id, run_id, lock_type, status,
                worktree_roots_json, binding_version, activated_at,
                updated_at, deactivated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (project_key, story_id, run_id, lock_type) DO UPDATE SET
                story_id = EXCLUDED.story_id,
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
    """Return the raw story-execution-lock row, or None."""

    with _connect_global() as conn:
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
# ControlPlaneOperationRecord rows
# ---------------------------------------------------------------------------


def save_control_plane_operation_global_row(row: dict[str, Any]) -> None:
    """Persist a control-plane-operation row dict globally.

    NOTE (AG3-054): this is the legacy upsert kept for direct test/contract use.
    The PRODUCTIVE terminal write goes through
    :func:`finalize_control_plane_operation_global_row` (ownership-scoped CAS), so
    a non-owner can never clobber a terminal/foreign row. The upsert always clears
    ``claimed_by`` (a stored row carries no live owner once it is saved as a
    terminal result).

    ERROR-3 fix (AG3-054): the upsert is CONDITIONAL -- it REFUSES to overwrite a
    row whose ``status='claimed'`` (a live, owned lease). Only the owner's
    ownership-scoped finalize/release may transition a claimed row. So a
    ``complete_phase`` / ``fail_phase`` (or any non-owner save) reusing a live
    ``start_phase`` op_id can no longer overwrite the claimed row and steal/destroy
    its ownership. The collision is surfaced fail-closed via
    :class:`ControlPlaneClaimCollisionError` (NO ERROR BYPASSING -- it is never a
    silent no-op). A fresh insert and an update of a TERMINAL (non-claimed) row are
    unaffected.

    Raises:
        ControlPlaneClaimCollisionError: When the row already exists and is still
            ``claimed`` (the upsert would have clobbered a live lease).
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            INSERT INTO control_plane_operations (
                op_id, project_key, story_id, run_id, session_id,
                operation_kind, phase, status, response_json,
                created_at, updated_at, claimed_by, claimed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (op_id) DO UPDATE SET
                project_key = EXCLUDED.project_key,
                story_id = EXCLUDED.story_id,
                run_id = EXCLUDED.run_id,
                session_id = EXCLUDED.session_id,
                operation_kind = EXCLUDED.operation_kind,
                phase = EXCLUDED.phase,
                status = EXCLUDED.status,
                response_json = EXCLUDED.response_json,
                updated_at = EXCLUDED.updated_at,
                claimed_by = EXCLUDED.claimed_by,
                claimed_at = EXCLUDED.claimed_at
            WHERE control_plane_operations.status <> 'claimed'
            """,
            (
                row["op_id"],
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["session_id"],
                row["operation_kind"],
                row["phase"],
                row["status"],
                row["response_json"],
                row["created_at"],
                row["updated_at"],
                row.get("claimed_by"),
                row.get("claimed_at"),
            ),
        )
        # rowcount == 1 on a fresh insert or a qualifying (non-claimed) update;
        # rowcount == 0 ONLY when the conflicting row is still ``claimed`` and the
        # WHERE blocked the overwrite. Fail-closed: a live claimed lease was hit.
        if int(cursor.rowcount) == 0:
            raise ControlPlaneClaimCollisionError(
                "control-plane operation save refused: op_id "
                f"{row['op_id']!r} is held by a LIVE 'claimed' lease; only the "
                "owner's finalize/release may transition it. A non-owner save "
                "(e.g. complete/fail reusing a live start's op_id) must not "
                "clobber the claim (AG3-054 ERROR-3, fail-closed).",
            )


def claim_control_plane_operation_global_row(row: dict[str, Any]) -> bool:
    """Atomically claim an op_id, inserting only if absent (AG3-054 leased claim).

    Performs a single ``INSERT ... ON CONFLICT (op_id) DO NOTHING`` with
    ``status='claimed'`` and the per-call ``claimed_by`` / ``claimed_at`` lease, so
    exactly ONE concurrent caller wins the claim for a given ``op_id``; the loser
    sees zero affected rows and must inspect the row (terminal => replay,
    live claim => in-flight rejection, expired claim => CAS takeover). The claim
    happens BEFORE dispatch, so a loser never dispatches.

    Returns:
        ``True`` iff this caller inserted the row (won the claim); ``False`` when
        the op_id already existed (a concurrent/earlier caller owns it).
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            INSERT INTO control_plane_operations (
                op_id, project_key, story_id, run_id, session_id,
                operation_kind, phase, status, response_json,
                created_at, updated_at, claimed_by, claimed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (op_id) DO NOTHING
            """,
            (
                row["op_id"],
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["session_id"],
                row["operation_kind"],
                row["phase"],
                row["status"],
                row["response_json"],
                row["created_at"],
                row["updated_at"],
                row.get("claimed_by"),
                row.get("claimed_at"),
            ),
        )
        return int(cursor.rowcount) == 1


def takeover_control_plane_operation_global_row(
    row: dict[str, Any],
    *,
    observed_claimed_by: str | None,
    observed_claimed_at: str | None,
) -> bool:
    """CAS-take over an EXPIRED claim (AG3-054 leased claim).

    Atomically re-stamps the lease to this caller ONLY if the row is still the
    exact ``claimed`` placeholder the caller observed (same ``claimed_by`` /
    ``claimed_at``). A concurrent winner that already finalized, released or took
    over changed one of those, so the CAS affects zero rows and this caller loses
    the takeover race (treated as an in-flight loser; it does NOT dispatch).

    Returns:
        ``True`` iff this caller took over the expired claim (rowcount == 1).
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            UPDATE control_plane_operations
            SET claimed_by = ?, claimed_at = ?, updated_at = ?
            WHERE op_id = ?
              AND status = 'claimed'
              AND claimed_by IS NOT DISTINCT FROM ?
              AND claimed_at IS NOT DISTINCT FROM ?
            """,
            (
                row.get("claimed_by"),
                row.get("claimed_at"),
                row["updated_at"],
                row["op_id"],
                observed_claimed_by,
                observed_claimed_at,
            ),
        )
        return int(cursor.rowcount) == 1


def finalize_control_plane_operation_global_row(
    row: dict[str, Any],
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
) -> bool:
    """Ownership-scoped terminal write of a claimed op (AG3-054 leased claim).

    Writes the terminal status + response_json and CLEARS ``claimed_by`` ONLY when
    the row is still ``claimed`` by ``owner_token``. If another owner finalized or
    took over the (expired) claim in between, the CAS affects zero rows and this
    caller must NOT overwrite the foreign/terminal row -- it returns ``False`` so
    the runtime surfaces a replay/rejection instead.

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW lease epoch the owner
    stamped) is given, the CAS also matches ``claimed_at`` (raw column) so it
    scopes to THIS lease generation -- a reused token / post-takeover stale owner
    cannot match a NEWER lease. ``None`` keeps the legacy owner-only CAS.

    Returns:
        ``True`` iff this owner's terminal write applied (rowcount == 1).
    """

    epoch_clause, epoch_params = _owner_epoch_cas_clause(owner_claimed_at)
    with _connect_global() as conn:
        # epoch_clause is a constant fragment, not user data.
        cursor = conn.execute(
            f"""
            UPDATE control_plane_operations
            SET status = ?, response_json = ?, updated_at = ?,
                run_id = ?, session_id = ?, phase = ?,
                claimed_by = NULL, claimed_at = NULL
            WHERE op_id = ?
              AND status = 'claimed'
              AND claimed_by = ?{epoch_clause}
            """,  # noqa: S608
            (
                row["status"],
                row["response_json"],
                row["updated_at"],
                row["run_id"],
                row["session_id"],
                row["phase"],
                row["op_id"],
                owner_token,
                *epoch_params,
            ),
        )
        return int(cursor.rowcount) == 1


def _owner_epoch_cas_clause(
    owner_claimed_at: str | None,
) -> tuple[str, tuple[str, ...]]:
    """Build the optional lease-epoch CAS fragment (AG3-054 WARNING-4, #4).

    When ``owner_claimed_at`` is given, returns a SQL fragment matching the RAW
    ``claimed_at`` column plus its bind parameter, so the ownership CAS scopes to
    THIS lease generation. When ``None`` (legacy administrative callers), returns
    an empty fragment so the CAS stays owner-only (backward compatible). The
    fragment is a fixed string with NO interpolated user data.
    """
    if owner_claimed_at is None:
        return "", ()
    return "\n              AND claimed_at IS NOT DISTINCT FROM ?", (owner_claimed_at,)


def _insert_session_binding_row(conn: _CompatConnection, row: dict[str, Any]) -> None:
    """Run-scoped insert/upsert of one session-run-binding row (AG3-054 sweep).

    The binding is keyed by ``session_id`` (one row per session) but carries
    ``(project_key, story_id, run_id)``. The conditional upsert creates the row when
    absent and updates it ONLY when the existing row already belongs to the SAME
    ``(project_key, story_id, run_id)``. A live binding for a DIFFERENT run that has
    since rebound the same ``session_id`` is NEVER overwritten: the
    ``DO UPDATE ... WHERE`` predicate is false, the statement touches zero rows, and
    a still-present foreign row makes this raise
    :class:`ControlPlaneBindingCollisionError` so the WHOLE atomic transaction rolls
    back (no foreign-binding clobber).

    Raises:
        ControlPlaneBindingCollisionError: When the session is bound to a DIFFERENT
            ``(project_key, story_id, run_id)`` (the upsert refused to overwrite).
    """
    cursor = conn.execute(
        """
        INSERT INTO session_run_bindings (
            session_id, project_key, story_id, run_id, principal_type,
            worktree_roots_json, binding_version, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (session_id) DO UPDATE SET
            principal_type = EXCLUDED.principal_type,
            worktree_roots_json = EXCLUDED.worktree_roots_json,
            binding_version = EXCLUDED.binding_version,
            updated_at = EXCLUDED.updated_at
        WHERE session_run_bindings.project_key = EXCLUDED.project_key
          AND session_run_bindings.story_id = EXCLUDED.story_id
          AND session_run_bindings.run_id = EXCLUDED.run_id
        """,
        (
            row["session_id"],
            row["project_key"],
            row["story_id"],
            row["run_id"],
            row["principal_type"],
            row["worktree_roots_json"],
            row["binding_version"],
            row["updated_at"],
        ),
    )
    if int(cursor.rowcount) == 0:
        # Zero rows == a conflicting row exists whose run did NOT match (a fresh
        # insert affects 1 row; a run-matched update affects 1 row). Confirm a
        # foreign row is present and fail closed -- never silently overwrite it.
        raise ControlPlaneBindingCollisionError(
            "control-plane session-binding save refused: session "
            f"{row['session_id']!r} is bound to a DIFFERENT run than "
            f"({row['project_key']!r}, {row['story_id']!r}, {row['run_id']!r}); a "
            "stale/late operation for an old run must not overwrite a live "
            "binding that has since rebound the same session_id (AG3-054 "
            "run-scoping, fail-closed).",
        )


def _run_scoped_delete_session_binding_row(
    conn: _CompatConnection,
    *,
    session_id: str,
    project_key: str,
    story_id: str,
    run_id: str,
) -> None:
    """Run-scoped delete of one session-run-binding row (AG3-054 sweep).

    Deletes the binding ONLY when its ``(project_key, story_id, run_id)`` matches the
    closing run. When the session has since been rebound to a DIFFERENT run, the
    live binding is left untouched and this raises
    :class:`ControlPlaneBindingCollisionError` so the WHOLE atomic teardown rolls
    back (no foreign run's regime is torn down). A missing binding is a benign no-op
    (idempotent closure).

    Raises:
        ControlPlaneBindingCollisionError: When a live binding exists for the
            session but belongs to a DIFFERENT run.
    """
    cursor = conn.execute(
        """
        DELETE FROM session_run_bindings
        WHERE session_id = ? AND project_key = ? AND story_id = ? AND run_id = ?
        """,
        (session_id, project_key, story_id, run_id),
    )
    if int(cursor.rowcount) == 1:
        return
    # Nothing matched the closing run: either there is no binding at all (benign
    # no-op) or a FOREIGN run rebound this session. Probe to distinguish.
    foreign = conn.execute(
        "SELECT run_id FROM session_run_bindings WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if foreign is not None:
        raise ControlPlaneBindingCollisionError(
            "control-plane session-binding delete refused: session "
            f"{session_id!r} is bound to run {foreign['run_id']!r}, not the "
            f"closing run {run_id!r}; closure must not tear down a foreign run's "
            "live binding (AG3-054 run-scoping, fail-closed).",
        )


def _insert_story_execution_lock_row(
    conn: _CompatConnection, row: dict[str, Any]
) -> None:
    """Insert/upsert one story-execution-lock row on an EXISTING connection (#1)."""
    conn.execute(
        """
        INSERT INTO story_execution_locks (
            project_key, story_id, run_id, lock_type, status,
            worktree_roots_json, binding_version, activated_at,
            updated_at, deactivated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (project_key, story_id, run_id, lock_type) DO UPDATE SET
            story_id = EXCLUDED.story_id,
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


def finalize_control_plane_start_phase_global_row(
    *,
    op_row: dict[str, Any],
    owner_token: str,
    owner_claimed_at: str | None = None,
    binding_row: dict[str, Any] | None,
    lock_rows: Sequence[dict[str, Any]],
    event_rows: Sequence[dict[str, Any]],
) -> bool:
    """Atomically CAS-finalize a start_phase AND materialize its side effects (#1).

    ERROR-1 fix (#1): the ownership CAS finalize and the start_phase side effects
    (session binding, story/QA locks, lifecycle events) are applied in ONE
    connection / ONE transaction, gated on STILL owning the claim. The CAS finalize
    runs FIRST: ``UPDATE ... WHERE op_id=? AND status='claimed' AND claimed_by=?``.

    * rowcount == 1 -> this owner still holds the claim: the binding / locks /
      events are inserted on the SAME connection and the whole transaction commits
      atomically. The terminal op and its canonical side effects appear together.
    * rowcount == 0 -> the claim was lost/taken-over (a slow owner whose lease
      expired and was finalized by a concurrent takeover): NOTHING is materialized
      and the transaction is rolled back (the ``with`` block raises before commit),
      so the loser writes NO duplicate/conflicting binding / lock / event. The
      runtime then surfaces the winner's terminal row as a replay.

    The loser therefore never writes canonical side effects -- materialization is
    ownership-gated and atomic with the finalize (FK-22 §22.9, FK-91).

    Args:
        op_row: The terminal control-plane operation row (committed result).
        owner_token: This caller's lease owner token (the CAS scope).
        owner_claimed_at: This caller's RAW lease epoch; when given, the ownership
            CAS also matches ``claimed_at`` so it scopes to THIS lease generation
            (WARNING-4, #4). ``None`` keeps the legacy owner-only CAS.
        binding_row: The session-run-binding row to materialize, or ``None`` for a
            fast story (no story-scoped binding).
        lock_rows: The story-execution / qa-artifact-write lock rows (empty for a
            fast story).
        event_rows: The lifecycle execution-event rows (empty for a fast story).

    AG3-054 run-scoping sweep: the binding INSERT is RUN-scoped
    (:func:`_insert_session_binding_row`). A start finalize for an OLD run can never
    overwrite a live binding that has since rebound the same ``session_id`` to a
    DIFFERENT run -- the conditional upsert raises
    :class:`ControlPlaneBindingCollisionError` and the whole transaction rolls back.

    Returns:
        ``True`` iff this owner's terminal write applied and the side effects were
        materialized atomically; ``False`` when the claim was lost (nothing written).

    Raises:
        ControlPlaneBindingCollisionError: When the binding would overwrite a
            FOREIGN run's live binding (nothing committed; the binding intact).
    """

    class _NotOwnerError(RuntimeError):
        """Internal sentinel: abort + roll back when the ownership CAS loses."""

    epoch_clause, epoch_params = _owner_epoch_cas_clause(owner_claimed_at)
    try:
        with _connect_global() as conn:
            cursor = conn.execute(
                f"""
                UPDATE control_plane_operations
                SET status = ?, response_json = ?, updated_at = ?,
                    run_id = ?, session_id = ?, phase = ?,
                    claimed_by = NULL, claimed_at = NULL
                WHERE op_id = ?
                  AND status = 'claimed'
                  AND claimed_by = ?{epoch_clause}
                """,  # noqa: S608 -- epoch_clause is a constant fragment
                (
                    op_row["status"],
                    op_row["response_json"],
                    op_row["updated_at"],
                    op_row["run_id"],
                    op_row["session_id"],
                    op_row["phase"],
                    op_row["op_id"],
                    owner_token,
                    *epoch_params,
                ),
            )
            if int(cursor.rowcount) != 1:
                # Lost the ownership CAS: roll back so NO side effect is written.
                raise _NotOwnerError
            if binding_row is not None:
                _insert_session_binding_row(conn, binding_row)
            for lock_row in lock_rows:
                _insert_story_execution_lock_row(conn, lock_row)
            for event_row in event_rows:
                _insert_execution_event_row(conn, event_row)
    except _NotOwnerError:
        return False
    return True


def _conditional_upsert_control_plane_op_row(
    conn: _CompatConnection, row: dict[str, Any]
) -> None:
    """Conditionally upsert a terminal op row on an EXISTING connection (ERROR-2).

    Shares the conditional-upsert semantics of
    :func:`save_control_plane_operation_global_row` (it REFUSES to overwrite a row
    that is still ``status='claimed'`` -- a live, owned lease) but runs on a
    CALLER-supplied connection so the op-row write and the mutation's side effects
    commit (or roll back) in ONE transaction. The collision is surfaced via
    :class:`ControlPlaneClaimCollisionError` raised INSIDE the transaction, so the
    enclosing ``with _connect_global()`` block re-raises before ``commit`` and the
    already-issued side-effect statements are rolled back -- no orphan binding /
    lock / event survives a collision (AG3-054 ERROR-2, fail-closed atomicity).

    Raises:
        ControlPlaneClaimCollisionError: When the conflicting row is still
            ``claimed`` (the upsert would have clobbered a live lease).
    """
    cursor = conn.execute(
        """
        INSERT INTO control_plane_operations (
            op_id, project_key, story_id, run_id, session_id,
            operation_kind, phase, status, response_json,
            created_at, updated_at, claimed_by, claimed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (op_id) DO UPDATE SET
            project_key = EXCLUDED.project_key,
            story_id = EXCLUDED.story_id,
            run_id = EXCLUDED.run_id,
            session_id = EXCLUDED.session_id,
            operation_kind = EXCLUDED.operation_kind,
            phase = EXCLUDED.phase,
            status = EXCLUDED.status,
            response_json = EXCLUDED.response_json,
            updated_at = EXCLUDED.updated_at,
            claimed_by = EXCLUDED.claimed_by,
            claimed_at = EXCLUDED.claimed_at
        WHERE control_plane_operations.status <> 'claimed'
        """,
        (
            row["op_id"],
            row["project_key"],
            row["story_id"],
            row["run_id"],
            row["session_id"],
            row["operation_kind"],
            row["phase"],
            row["status"],
            row["response_json"],
            row["created_at"],
            row["updated_at"],
            row.get("claimed_by"),
            row.get("claimed_at"),
        ),
    )
    if int(cursor.rowcount) == 0:
        raise ControlPlaneClaimCollisionError(
            "control-plane operation save refused: op_id "
            f"{row['op_id']!r} is held by a LIVE 'claimed' lease; only the "
            "owner's finalize/release may transition it. A non-owner save "
            "(e.g. complete/fail/closure reusing a live start's op_id) must not "
            "clobber the claim (AG3-054 ERROR-3, fail-closed).",
        )


def commit_control_plane_operation_with_side_effects_global_row(
    *,
    op_row: dict[str, Any],
    binding_to_save: dict[str, Any] | None,
    binding_to_delete: dict[str, Any] | None,
    lock_rows: Sequence[dict[str, Any]],
    event_rows: Sequence[dict[str, Any]],
) -> None:
    """Atomically commit a terminal op AND its side effects in ONE transaction (#2).

    ERROR-2 fix (#2): ``complete_phase`` / ``fail_phase`` (the admitted-phase
    mutation) and ``complete_closure`` (standard + fast teardown) previously wrote
    their side effects (session-binding create/delete, lock records, lifecycle
    events) via SEPARATE ``_connect_global()`` transactions and THEN called the
    conditional op-row upsert -- which raises :class:`ControlPlaneClaimCollisionError`
    when it would clobber a LIVE ``claimed`` start lease. By then the side effects
    were already committed -> orphan state (e.g. a deleted binding / deactivated
    lock while the live claim survived and the result was a rejection).

    This function applies the conditional op-row upsert AND all side effects on the
    SAME connection / ONE transaction, with the collision gate running FIRST: a
    collision raises before any commit, so the whole transaction (including every
    side effect) rolls back. The mutation is therefore atomic -- a collision leaves
    NO side effect written and the live claimed row intact (FK-22 §22.9).

    Args:
        op_row: The terminal control-plane operation row (committed result).
        binding_to_save: A session-run-binding row to RUN-scoped-upsert, or ``None``
            (the complete/fail standard path materializes one; closure never does).
            A foreign-run conflict raises :class:`ControlPlaneBindingCollisionError`.
        binding_to_delete: A run-scoped delete spec dict (``session_id`` +
            ``project_key`` + ``story_id`` + ``run_id``) whose binding must be
            removed, or ``None`` (closure removes the binding; complete/fail never
            does). A foreign-run live binding is left untouched and raises
            :class:`ControlPlaneBindingCollisionError`.
        lock_rows: The story/QA lock rows to upsert (empty when none apply).
        event_rows: The lifecycle execution-event rows to append (empty for none).

    Raises:
        ControlPlaneClaimCollisionError: When ``op_row`` collides with a LIVE
            ``claimed`` lease (nothing is committed; the live claim is intact).
        ControlPlaneBindingCollisionError: When the binding save/delete would touch
            a FOREIGN run's live binding (nothing committed; the binding intact).
    """
    with _connect_global() as conn:
        # Collision gate FIRST: a live-claim collision raises here, BEFORE any side
        # effect is durable, so the transaction rolls back with zero orphan state.
        _conditional_upsert_control_plane_op_row(conn, op_row)
        if binding_to_save is not None:
            _insert_session_binding_row(conn, binding_to_save)
        if binding_to_delete is not None:
            # Run-scoped delete: a foreign run's live binding raises and rolls back
            # the WHOLE transaction (no foreign teardown, no orphan op/lock/event).
            _run_scoped_delete_session_binding_row(
                conn,
                session_id=str(binding_to_delete["session_id"]),
                project_key=str(binding_to_delete["project_key"]),
                story_id=str(binding_to_delete["story_id"]),
                run_id=str(binding_to_delete["run_id"]),
            )
        for lock_row in lock_rows:
            _insert_story_execution_lock_row(conn, lock_row)
        for event_row in event_rows:
            _insert_execution_event_row(conn, event_row)


def release_control_plane_operation_global_row(
    op_id: str,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
) -> None:
    """Ownership-scoped release of a claimed op (AG3-054 leased claim).

    Deletes the row ONLY when it is still ``claimed`` by ``owner_token``. NEVER an
    unconditional delete: a terminal row (``status != 'claimed'``) and another
    owner's claim are both left untouched, so a release on the exception/rejection
    path can never delete a foreign or committed result. Idempotent.

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW lease epoch the owner
    stamped) is given, the delete CAS also matches ``claimed_at`` so it scopes to
    THIS lease generation -- a stale owner (reused token / post-takeover) cannot
    delete a NEWER lease. ``None`` keeps the legacy owner-only CAS.
    """

    epoch_clause, epoch_params = _owner_epoch_cas_clause(owner_claimed_at)
    with _connect_global() as conn:
        # epoch_clause is a constant fragment, not user data.
        conn.execute(
            f"""
            DELETE FROM control_plane_operations
            WHERE op_id = ? AND status = 'claimed' AND claimed_by = ?{epoch_clause}
            """,  # noqa: S608
            (op_id, owner_token, *epoch_params),
        )


def delete_control_plane_operation_global_row(op_id: str) -> None:
    """Unconditional delete of a control-plane-operation row by op_id.

    Retained for administrative recovery only (it ignores ownership/status). The
    PRODUCTIVE release path uses
    :func:`release_control_plane_operation_global_row` (ownership-scoped).
    Idempotent: deleting an absent op_id is a no-op.
    """

    with _connect_global() as conn:
        conn.execute(
            "DELETE FROM control_plane_operations WHERE op_id = ?",
            (op_id,),
        )


def has_committed_control_plane_operation_for_run_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
) -> bool:
    """Whether a committed setup ``phase_start`` exists for THIS run (AG3-054 #3).

    ERROR-3 fix (#3): admission evidence must prove an admitted START, not merely
    that ANY committed op exists for the run. A committed ``phase_complete`` /
    ``closure_complete`` with no committed start would otherwise bootstrap
    admission from thin air. The probe is therefore narrowed to the ONLY operation
    the pre-start guard gates: a ``committed`` ``phase_start`` of phase ``setup``
    for the exact ``(project_key, story_id, run_id)``. A ``claimed`` placeholder,
    a ``rejected`` row, and a non-setup / non-start committed op are NOT evidence.
    """

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM control_plane_operations
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND status = 'committed'
              AND operation_kind = 'phase_start'
              AND phase = 'setup'
            LIMIT 1
            """,
            (project_key, story_id, run_id),
        ).fetchone()
    return row is not None


def has_committed_story_exit_operation_for_run_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
) -> bool:
    """Whether a committed story-exit terminal marker exists for THIS run."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM control_plane_operations
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND status = 'committed'
              AND operation_kind = 'story_exit'
            LIMIT 1
            """,
            (project_key, story_id, run_id),
        ).fetchone()
    return row is not None


def load_control_plane_operation_global_row(
    op_id: str,
) -> dict[str, Any] | None:
    """Return the raw control-plane-operation row, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM control_plane_operations
            WHERE op_id = ?
            """,
            (op_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


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
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
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

    del store_dir
    with _connect_global() as conn:
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
    if row is None:
        return None
    return dict(row)


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


def pg_execute_stage_upsert(conn: Any, row: dict[str, Any]) -> None:
    """Upsert a ``qa_stage_results`` row on an existing psycopg connection.

    Driver-owned SQL (FK-69 §69.4). Callable both from the in-transaction
    batch path (``persist_layer_artifact_rows``) and from the
    ``boundary.state_backend_repository`` Facade repos (R -> T), so the SQL
    lives exactly once in the driver (SSOT; AC010: the driver never imports a
    repository).

    Args:
        conn: Open psycopg connection (driver transaction).
        row: Fully serialised ``qa_stage_results`` row (dict).
    """
    conn.execute(
        """
        INSERT INTO qa_stage_results (
            project_key, story_id, run_id, attempt_no, stage_id, layer,
            producer_component, status, blocking, total_checks,
            failed_checks, warning_checks, artifact_id, recorded_at
        ) VALUES (
            %(project_key)s, %(story_id)s, %(run_id)s, %(attempt_no)s,
            %(stage_id)s, %(layer)s, %(producer_component)s, %(status)s,
            %(blocking)s, %(total_checks)s, %(failed_checks)s,
            %(warning_checks)s, %(artifact_id)s, %(recorded_at)s
        )
        ON CONFLICT (project_key, run_id, attempt_no, stage_id)
        DO UPDATE SET
            story_id=EXCLUDED.story_id,
            layer = EXCLUDED.layer,
            producer_component = EXCLUDED.producer_component,
            status = EXCLUDED.status,
            blocking = EXCLUDED.blocking,
            total_checks = EXCLUDED.total_checks,
            failed_checks = EXCLUDED.failed_checks,
            warning_checks = EXCLUDED.warning_checks,
            artifact_id = EXCLUDED.artifact_id,
            recorded_at = EXCLUDED.recorded_at
        """,
        row,
    )


def pg_execute_finding_upsert(conn: Any, row: dict[str, Any]) -> None:
    """Upsert a ``qa_findings`` row on an existing psycopg connection.

    Driver-owned SQL (FK-69 §69.4). See :func:`pg_execute_stage_upsert` for the
    SSOT / AC010 rationale.

    Args:
        conn: Open psycopg connection (driver transaction).
        row: Fully serialised ``qa_findings`` row (dict).
    """
    conn.execute(
        """
        INSERT INTO qa_findings (
            project_key, story_id, run_id, attempt_no, stage_id,
            finding_id, check_id, status, severity, blocking,
            source_component, artifact_id, occurred_at,
            category, reason, description, detail, metadata_json
        ) VALUES (
            %(project_key)s, %(story_id)s, %(run_id)s, %(attempt_no)s,
            %(stage_id)s, %(finding_id)s, %(check_id)s, %(status)s,
            %(severity)s, %(blocking)s, %(source_component)s,
            %(artifact_id)s, %(occurred_at)s, %(category)s, %(reason)s,
            %(description)s, %(detail)s, %(metadata_json)s
        )
        ON CONFLICT (project_key, run_id, attempt_no, stage_id, finding_id)
        DO UPDATE SET
            story_id=EXCLUDED.story_id,
            check_id = EXCLUDED.check_id,
            status = EXCLUDED.status,
            severity = EXCLUDED.severity,
            blocking = EXCLUDED.blocking,
            source_component = EXCLUDED.source_component,
            artifact_id = EXCLUDED.artifact_id,
            occurred_at = EXCLUDED.occurred_at,
            category = EXCLUDED.category,
            reason = EXCLUDED.reason,
            description = EXCLUDED.description,
            detail = EXCLUDED.detail,
            metadata_json = EXCLUDED.metadata_json
        """,
        row,
    )


def pg_delete_findings_for_scope(
    conn: Any,
    *,
    project_key: str,
    run_id: str,
    attempt_no: int,
    stage_id: str,
) -> None:
    """Delete ``qa_findings`` for a scope on an existing psycopg connection.

    Driver-owned SQL (FK-69). Removes stale findings before a batch re-write so
    no outdated rows survive (idempotency invariant of the batch write).

    Args:
        conn: Open psycopg connection (driver transaction).
        project_key: Project key.
        run_id: Run ID.
        attempt_no: Attempt number.
        stage_id: Layer / stage ID.
    """
    conn.execute(
        """
        DELETE FROM qa_findings
        WHERE project_key = %s AND run_id = %s AND attempt_no = %s AND stage_id = %s
        """,
        (project_key, run_id, attempt_no, stage_id),
    )


def persist_layer_artifact_rows(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    layer_payload_rows: list[dict[str, object]],
    attempt_nr: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist QA layer artifact rows, FK-69 read models, and projection files.

    ``layer_payload_rows`` contains pre-serialized dicts from the mapper layer.
    Each element has keys: ``layer``, ``artifact_name``, ``producer_component``,
    ``payload``, ``passed``, ``recorded_at``, ``stage_row``, ``finding_rows``.

    Finding D (AG3-035 remediation): FK-69 row persistence runs through the
    driver-owned upsert/delete functions (``pg_execute_stage_upsert``,
    ``pg_execute_finding_upsert``, ``pg_delete_findings_for_scope`` in this
    module). The transaction stays in the driver (FAIL-CLOSED: stage+findings+
    artifact_records atomic in ONE transaction). The accessor repos
    (boundary.state_backend_repository) delegate their Postgres write path
    to the same functions -- the SQL lives exactly once in the driver (SSOT;
    AC010: the driver imports no repository).
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist QA layer artifacts without story context "
            "in canonical backend",
        )
    if flow_row is None:
        raise CorruptStateError(
            "Cannot materialize FK-69 QA read models without flow execution "
            "scope in canonical Postgres backend",
        )
    produced: list[str] = []
    with _connect(story_dir) as conn:
        for item in layer_payload_rows:
            layer = str(item["layer"])
            artifact_name = str(item["artifact_name"])
            payload = cast("_JsonRecord", item["payload"])
            target_dir = projection_dir or story_dir
            _write_projection(target_dir / artifact_name, payload)
            artifact_id = _artifact_id_for(layer, attempt_nr)
            # FK-69: delete old findings for this scope + layer (driver-owned SQL)
            pg_delete_findings_for_scope(
                conn,
                project_key=str(flow_row["project_key"]),
                run_id=str(flow_row["run_id"]),
                attempt_no=attempt_nr,
                stage_id=layer,
            )
            # Rebuild stage_row and finding_rows with the real artifact_id
            stage_row = cast("dict[str, object] | None", item.get("stage_row"))
            finding_rows = cast(
                "list[dict[str, object]]", item.get("finding_rows") or []
            )
            if stage_row is not None:
                updated_stage = dict(stage_row)
                updated_stage["artifact_id"] = artifact_id
                pg_execute_stage_upsert(conn, updated_stage)
            for fr in finding_rows:
                updated_fr = dict(fr)
                updated_fr["artifact_id"] = artifact_id
                pg_execute_finding_upsert(conn, updated_fr)
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

    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist verify decision without story context in canonical backend",
        )
    if flow_row is None:
        raise CorruptStateError(
            "Cannot persist verify decision artifact without flow execution "
            "scope in canonical Postgres backend",
        )
    target_dir = projection_dir or story_dir
    _write_projection(target_dir / VERIFY_DECISION_FILE, canonical_payload)
    written = (VERIFY_DECISION_FILE,)
    with _connect(story_dir) as conn:
        recorded_at = datetime.fromisoformat(now_iso())
        conn.execute(
            """
            INSERT INTO decision_records (
                project_key, story_id, run_id, flow_id, decision_kind,
                attempt_nr, status, passed, summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, run_id, decision_kind, attempt_nr)
            DO UPDATE SET
                story_id=excluded.story_id,
                flow_id=excluded.flow_id,
                status=excluded.status,
                passed=excluded.passed,
                summary=excluded.summary,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                flow_row["project_key"],
                story_id,
                flow_row["run_id"],
                flow_row["flow_id"],
                "verify",
                attempt_nr,
                decision_row["status"],
                1 if decision_row["passed"] else 0,
                decision_row["summary"],
                _dump_json(canonical_payload),
                recorded_at.isoformat(),
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
    flow_row = load_flow_execution_row(story_dir)
    with _connect(story_dir) as conn:
        if flow_row is not None:
            row = conn.execute(
                """
                SELECT payload_json
                FROM decision_records
                WHERE project_key = ? AND story_id = ? AND run_id = ?
                  AND decision_kind = 'verify'
                ORDER BY attempt_nr DESC
                LIMIT 1
                """,
                (flow_row["project_key"], flow_row["story_id"], flow_row["run_id"]),
            ).fetchone()
            if row is None:
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
        else:
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
            f"decision_records payload is invalid in {_database_label()}: {exc}",
        ) from exc


def load_latest_verify_decision_payload_for_scope(
    scope: RuntimeStateScope,
) -> dict[str, object] | None:
    """Return the latest verify-decision payload for a scope, or None."""

    with _connect(scope.story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json
            FROM decision_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND decision_kind = 'verify'
            ORDER BY attempt_nr DESC
            LIMIT 1
            """,
            (scope.project_key, scope.story_id, scope.run_id),
        ).fetchone()
    if row is None:
        return None
    try:
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"decision_records payload is invalid in {_database_label()}: {exc}",
        ) from exc


def load_artifact_record_payload(
    story_dir: Path,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Return the latest QA artifact payload from artifact_envelopes for a kind.

    Maps artifact_kind ("structural"/"semantic"/"adversarial") to stage
    "qa-layer-{kind}" and reads from artifact_envelopes (AG3-023 3.4.0).
    Uses run_id from current flow execution when available for scoped lookup.
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    stage = f"qa-layer-{artifact_kind}"
    flow_row = load_flow_execution_row(story_dir)
    with _connect(story_dir) as conn:
        if flow_row is not None:
            row = conn.execute(
                """
                SELECT payload_json
                FROM artifact_envelopes
                WHERE story_id = ? AND run_id = ? AND stage = ?
                ORDER BY attempt DESC
                LIMIT 1
                """,
                (story_id, flow_row["run_id"], stage),
            ).fetchone()
            if row is None:
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
        else:
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
        result = raw if isinstance(raw, dict) else json.loads(str(raw))
        return _cast_json_record(result)
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"artifact_envelopes payload is invalid in {_database_label()}: {exc}",
        ) from exc


def load_artifact_record_payload_for_scope(
    scope: RuntimeStateScope,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Return the latest artifact payload for a scope and kind from artifact_envelopes."""

    stage = f"qa-layer-{artifact_kind}"
    with _connect(scope.story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json
            FROM artifact_envelopes
            WHERE story_id = ? AND run_id = ? AND stage = ?
            ORDER BY attempt DESC
            LIMIT 1
            """,
            (scope.story_id, scope.run_id, stage),
        ).fetchone()
    if row is None:
        return None
    raw = row["payload_json"]
    if raw is None:
        return None
    try:
        result = raw if isinstance(raw, dict) else json.loads(str(raw))
        return _cast_json_record(result)
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"artifact_envelopes payload is invalid in {_database_label()}: {exc}",
        ) from exc


def persist_closure_report_row(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    report_row: dict[str, Any],
    projection_dir: Path | None = None,
) -> Path:
    """Persist a closure-report and write the projection file."""

    if flow_row is None:
        raise CorruptStateError(
            "Cannot persist closure artifact without flow execution scope "
            "in canonical Postgres backend",
        )
    target_dir = projection_dir or story_dir
    path = target_dir / CLOSURE_REPORT_FILE
    payload = cast("_JsonRecord", report_row["payload"])
    _write_projection(path, payload)
    return path


# ---------------------------------------------------------------------------
# QA read models (Postgres-only)
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
    """Return QA stage result row dicts matching the given filters."""

    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if attempt_no is not None:
        clauses.append("attempt_no = ?")
        params.append(attempt_no)
    if stage_id is not None:
        clauses.append("stage_id = ?")
        params.append(stage_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM qa_stage_results
            {where_clause}
            ORDER BY attempt_no ASC, stage_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def load_qa_finding_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return QA finding row dicts matching the given filters."""

    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if attempt_no is not None:
        clauses.append("attempt_no = ?")
        params.append(attempt_no)
    if stage_id is not None:
        clauses.append("stage_id = ?")
        params.append(stage_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM qa_findings
            {where_clause}
            ORDER BY attempt_no ASC, stage_id ASC, occurred_at ASC, finding_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Backend predicate helpers (kept as thin wrappers for driver-level checks)
# ---------------------------------------------------------------------------


def backend_has_valid_context(story_dir: Path) -> bool:
    return load_story_context_row(story_dir) is not None


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return load_phase_state_row(story_dir) is not None
