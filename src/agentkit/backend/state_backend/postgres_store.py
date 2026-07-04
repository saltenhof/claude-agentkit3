"""PostgreSQL-backed canonical runtime store with JSON projections.

This module is a T-bloodtype infrastructure driver.
It MUST NOT import BC-Records (A-bloodtype components).
All BC-Record <-> dict conversions live in
``agentkit.backend.state_backend.store.mappers`` (boundary.state_backend_repository).

The sole sanctioned cross-import is the scalar persistence-boundary regex constant
``ownership.BINDING_VERSION_SQL_CHECK`` (a ``str``, not a record type; no
record <-> dict conversion crosses the boundary). It is imported so the DDL CHECK
constraint the driver installs on ``session_run_bindings.binding_version`` is
single-sourced from the SAME canonical value as the record-boundary predicate
``ownership.is_canonical_binding_version`` — the two encodings cannot drift
(Codex target-3 / SSOT).
"""

from __future__ import annotations

import atexit
import json
import os
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from agentkit.backend.boundary.filesystem import atomic_write_json, load_json_object
from agentkit.backend.boundary.shared.time import now_iso
from agentkit.backend.control_plane.ownership import BINDING_VERSION_SQL_CHECK
from agentkit.backend.core_types.qa_artifact_names import VERIFY_DECISION_FILE
from agentkit.backend.exceptions import (
    ControlPlaneBindingCollisionError,
    ControlPlaneClaimCollisionError,
    CorruptStateError,
)
from agentkit.backend.state_backend.config import (
    STATE_DATABASE_URL_ENV,
    load_state_backend_config,
    resolve_schema_name,
)
from agentkit.backend.state_backend.paths import (
    CLOSURE_REPORT_FILE,
    CONTEXT_EXPORT_FILE,
    PHASE_STATE_EXPORT_FILE,
)
from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    import psycopg

    from agentkit.backend.state_backend.scope import RuntimeStateScope


_PROJECT_KEY_FILTER = "project_key = ?"
_STORY_ID_FILTER = "story_id = ?"
_RUN_ID_FILTER = "run_id = ?"
_SCHEMA_ENSURE_LOCK = threading.Lock()
_SCHEMA_ENSURED_NAMES: set[str] = set()
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


# ---------------------------------------------------------------------------
# Process-bound connection pool (connection-churn elimination)
# ---------------------------------------------------------------------------
#
# Before: ``_connect_global`` opened a fresh ``psycopg.connect`` on EVERY store
# operation and closed it on block exit. Under the Postgres test suites (and any
# concurrent control-plane request load) that connect-per-operation model drove
# massive connection churn — every open/close crosses the Docker-Desktop userspace
# port proxy (``com.docker.backend`` / gvisor / vpnkit), which is the ~19-core CPU
# burn this hardening removes.
#
# Now: a single process-bound :class:`psycopg_pool.ConnectionPool` lends and
# returns connections. Transaction / CAS semantics are IDENTICAL to the former
# model — every ``with _connect_global()`` block still runs in its OWN transaction
# (committed at block end, rolled back on exception) and there is no nesting (a
# single acquisition per call stack; verified), so a size-1 pool cannot
# self-deadlock. ``_reset_pooled_connection`` scrubs session state on return so no
# ``search_path`` / GUC carries across borrows.
#
# Default ``max_size=1`` => at most ONE physical connection per process/worker. The
# CAS / ownership machinery serializes concurrent callers via DURABLE claim rows +
# row-level CAS (concept §10.5: "genau eine aktive Control-Plane-Writer-Instanz pro
# Datenbank"; reads take no locks), NOT via connection state, so a single connection
# yields identical outcomes — only serialized. The concurrent control-plane HTTP
# server (thread-per-request) can lift the ceiling for throughput via
# ``AGENTKIT_STATE_POOL_MAX_SIZE``; because no path acquires a second connection while
# holding one, raising the ceiling never introduces a deadlock and never changes a
# transaction boundary.
_STATE_POOL_MAX_SIZE_ENV = "AGENTKIT_STATE_POOL_MAX_SIZE"
_DEFAULT_STATE_POOL_MAX_SIZE = 1
_POOL_LOCK = threading.Lock()
_POOL: ConnectionPool[psycopg.Connection[Any]] | None = None
_POOL_URL: str | None = None


def _resolve_state_pool_max_size() -> int:
    """Resolve the per-process pool ceiling (default 1 = one connection/worker)."""

    raw = os.environ.get(_STATE_POOL_MAX_SIZE_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_STATE_POOL_MAX_SIZE
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid {_STATE_POOL_MAX_SIZE_ENV}={raw!r}; expected a positive integer.",
        ) from exc
    if value < 1:
        raise RuntimeError(
            f"Invalid {_STATE_POOL_MAX_SIZE_ENV}={value}; the pool must allow at "
            "least one connection.",
        )
    return value


def _reset_pooled_connection(conn: psycopg.Connection[Any]) -> None:
    """Scrub per-borrow session state before a connection re-enters the pool.

    Discards any lingering transaction and resets every session GUC (notably
    ``search_path``, which each borrow re-establishes via
    :func:`ensure_versioned_schema`). Guarantees no session-state carry-over
    (``search_path`` / GUC leakage) between pooled borrows.
    """

    if conn.closed:
        return
    conn.rollback()
    conn.execute("RESET ALL")
    conn.commit()


def _build_state_pool(url: str) -> ConnectionPool[psycopg.Connection[Any]]:
    pool: ConnectionPool[psycopg.Connection[Any]] = ConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=_resolve_state_pool_max_size(),
        kwargs={"row_factory": dict_row},
        reset=_reset_pooled_connection,
        check=ConnectionPool.check_connection,
        name="agentkit-state-backend",
        open=False,
    )
    pool.open()
    return pool


def _get_pool() -> ConnectionPool[psycopg.Connection[Any]]:
    """Return the process-bound connection pool for the active database URL.

    The pool is rebuilt only when the resolved URL changes (test env switching);
    within a process/worker bound to one URL it is reused, so exactly one physical
    connection (at the default ``max_size=1``) is held for the worker's lifetime.
    """

    global _POOL, _POOL_URL
    url = _database_url()
    with _POOL_LOCK:
        if _POOL is not None and url == _POOL_URL:
            return _POOL
        if _POOL is not None:
            _POOL.close()
        _POOL = _build_state_pool(url)
        _POOL_URL = url
        return _POOL


def _dispose_pool() -> None:
    """Close and forget the process-bound pool (atexit / test teardown)."""

    global _POOL, _POOL_URL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.close()
        _POOL = None
        _POOL_URL = None


atexit.register(_dispose_pool)


@contextmanager
def _connect_global() -> Iterator[_CompatConnection]:
    # Borrow from the process-bound pool instead of opening a fresh connection per
    # operation (connection-churn elimination). ``pool.connection()`` commits on a
    # clean exit, rolls back on exception, and RETURNS the connection to the pool
    # (never closes it); ``_reset_pooled_connection`` scrubs session state on return.
    # The staged commits below are unchanged and load-bearing: they release the
    # global DDL advisory lock before the heavy table/index bootstrap so parallel
    # schemas do not serialize behind one worker.
    pool = _get_pool()
    with pool.connection() as conn:
        compat = _CompatConnection(conn)
        _ensure_versioned_schema(compat)
        conn.commit()
        _ensure_schema_once(compat)
        conn.commit()
        yield compat
        conn.commit()


@contextmanager
def _connect(story_dir: Path) -> Iterator[_CompatConnection]:
    del story_dir
    with _connect_global() as compat:
        yield compat


@contextmanager
def borrow_repository_connection() -> Iterator[psycopg.Connection[Any]]:
    """Borrow the process-bound pool connection for a StateBackend repository op.

    ONE connection way for the whole backend (FIX THE MODEL): the ``StateBackend*``
    repositories under ``state_backend.store`` share the SAME process-bound pool as
    the store instead of each opening a fresh ``psycopg.connect`` per operation. A
    worker therefore holds at most ONE physical connection (default ``max_size=1``)
    across store AND repository work, closing the "a repo op opens a SECOND transient
    connection" gap.

    This is the sanctioned StateBackendRepository -> StateBackendDrivers edge (the
    repos already import ``schema_bootstrap.ensure_versioned_schema`` from the same
    driver boundary). The borrow performs NO schema work itself: it yields the pooled
    raw connection and lets EACH repository run its own bootstrap
    (``ensure_versioned_schema`` and its per-repo ``CREATE TABLE IF NOT EXISTS`` /
    ``_ensure_schema_once``) exactly as before — so every repository's schema,
    ``search_path`` and DDL behaviour is unchanged; only the connection ACQUISITION
    moves to the pool.

    Transaction semantics are identical to the former connect-per-op model: the block
    commits on a clean exit and the pool's ``reset`` (``_reset_pooled_connection``,
    which runs ``conn.rollback()`` first) discards an uncommitted transaction on an
    exception. The connection is RETURNED to the pool (never closed), and ``RESET
    ALL`` scrubs session state so ``search_path`` starts each borrow at the same
    default a fresh connection would carry. Rows are ``dict_row`` (the pool default),
    matching every repository's dict-keyed row access — no per-repo row_factory
    override is required. No repository path acquires a second pooled connection while
    holding one (verified: no Store<->Repo and no Repo<->Repo nesting), so the size-1
    pool cannot self-deadlock.
    """
    pool = _get_pool()
    with pool.connection() as conn:
        yield conn
        conn.commit()


@contextmanager
def _borrow_pooled_connection_raw() -> Iterator[psycopg.Connection[Any]]:
    """Borrow the pooled raw connection WITHOUT running the schema bootstrap.

    Sanctioned maintenance seam (e.g. the Postgres test fixture's per-test
    TRUNCATE): it reuses the SAME pooled connection as store operations — so it adds
    NO connection churn — but deliberately SKIPS ``_ensure_versioned_schema`` /
    ``_ensure_schema_once``. Skipping the bootstrap is required, not merely an
    optimisation: running it here would populate the process schema-bootstrap cache
    (``_SCHEMA_ENSURED_NAMES``) BEFORE the caller mutates the schema (e.g. a TRUNCATE
    that empties ``schema_versions``), which would then suppress the legitimate
    re-bootstrap on the NEXT store operation. Callers must address objects by
    QUALIFIED ``schema.table`` — this connection carries no guaranteed
    ``search_path``. Commits on clean exit; ``pool.connection()`` rolls back on
    exception.
    """
    pool = _get_pool()
    with pool.connection() as conn:
        yield conn
        conn.commit()


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
    schema_name = current_schema_name()
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
        "backend_instance_identity",
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
        # AG3-054 (SCHEMA_VERSION 3.20.0, FK-91 / FK-22 §22.9): the
        # owner-scoped claim. A fresh schema gets these from CREATE TABLE; an
        # existing same-version schema gets them idempotently here. TEXT (not
        # TIMESTAMPTZ) for claimed_at matches the table's other instants
        # (created_at/updated_at) so the ownership-scoped finalize/release CAS
        # (AG3-054 WARNING-4) exact-match roundtrips through plain ISO-8601 text.
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
        # AG3-137 (Session-Ownership schema foundation, Postgres-only K5): the
        # new tables come from postgres_schema.sql CREATE TABLE IF NOT EXISTS; the
        # ADDITIVE columns on the two pre-existing control-plane tables are
        # applied idempotently here for an existing same-version schema. All are
        # nullable / DEFAULT so a DB pre-populated with legacy rows survives
        # losslessly (AK3/AK4).
        (
            "ALTER TABLE session_run_bindings "
            "ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'"
        ),
        (
            "ALTER TABLE session_run_bindings "
            "ADD COLUMN IF NOT EXISTS revocation_reason TEXT"
        ),
        (
            "ALTER TABLE control_plane_operations "
            "ADD COLUMN IF NOT EXISTS operation_epoch INTEGER"
        ),
        (
            "ALTER TABLE control_plane_operations "
            "ADD COLUMN IF NOT EXISTS backend_instance_id TEXT"
        ),
        (
            "ALTER TABLE control_plane_operations "
            "ADD COLUMN IF NOT EXISTS instance_incarnation INTEGER"
        ),
        (
            "ALTER TABLE control_plane_operations "
            "ADD COLUMN IF NOT EXISTS declared_serialization_scope TEXT"
        ),
        (
            "ALTER TABLE control_plane_operations "
            "ADD COLUMN IF NOT EXISTS finalized_at TEXT"
        ),
        # AG3-140 (unified idempotency contract): the ``request_body_hash`` column
        # + the ``story_id`` NOT-NULL relaxation on the inflight-operation-record.
        # A fresh schema gets both from postgres_schema.sql CREATE TABLE; an
        # existing same-version schema gets them idempotently here. Additive /
        # lossless on a pre-populated DB (every existing row keeps its non-null
        # story_id; DROP NOT NULL on an already-nullable column is a no-op).
        (
            "ALTER TABLE control_plane_operations "
            "ADD COLUMN IF NOT EXISTS request_body_hash TEXT"
        ),
        (
            "ALTER TABLE control_plane_operations "
            "ALTER COLUMN story_id DROP NOT NULL"
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
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        (f"agentkit_postgres_schema_ddl:{current_schema_name()}",),
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
        "UPDATE session_run_bindings SET status = 'active' "
        "WHERE status IS NULL OR status = ''",
    )
    conn.execute(
        # Normalise every NON-canonical legacy value (random bind-<uuid4>, empty,
        # '0', leading-zero forms) to the initial version '1' so the canonical
        # value domain holds before the CHECK constraint is added in
        # _ensure_session_binding_constraints (Codex ERROR §4 follow-through). The
        # regex is single-sourced from ownership.BINDING_VERSION_SQL_CHECK (a
        # trusted module constant, not user input) so it cannot drift from the
        # CHECK the same bootstrap installs below (target-3 / SSOT).
        "UPDATE session_run_bindings SET binding_version = '1' "
        f"WHERE binding_version !~ '{BINDING_VERSION_SQL_CHECK}'",
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
                title,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, story_id) DO UPDATE SET
                story_uuid=excluded.story_uuid,
                story_number=excluded.story_number,
                story_type=excluded.story_type,
                execution_route=excluded.execution_route,
                implementation_contract=excluded.implementation_contract,
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
                title,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, story_id) DO UPDATE SET
                story_uuid=excluded.story_uuid,
                story_number=excluded.story_number,
                story_type=excluded.story_type,
                execution_route=excluded.execution_route,
                implementation_contract=excluded.implementation_contract,
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
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return execution-event row dicts matching the given filters.

    When *limit* is ``None`` rows are ordered ``occurred_at ASC, event_id ASC``
    (chronological — default for existing callers such as closure).  When *limit*
    is set to a positive integer the query flips to ``ORDER BY occurred_at DESC,
    event_id DESC LIMIT limit`` so the *most-recent* rows are returned first
    (FK-35 §35.3.5 rolling-window semantics).  A non-positive *limit* returns
    an empty list immediately.
    """
    if limit is not None and limit <= 0:
        return []
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
    if limit is not None:
        params.append(limit)
        order_and_limit = "ORDER BY occurred_at DESC, event_id DESC LIMIT ?"
    else:
        order_and_limit = "ORDER BY occurred_at ASC, event_id ASC"
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT project_key, story_id, run_id, event_id, event_type,
                   occurred_at, source_component, severity, phase, flow_id,
                   node_id, payload_json
            FROM execution_events
            {where_clause}
            {order_and_limit}
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def max_adjudication_occurred_at(
    story_dir: Path,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    payload_signal_type: str,
) -> str | None:
    """Return MAX(occurred_at) for governance_adjudication rows matching the exact scope.

    Implements FK-35 §35.3.11: the last adjudication timestamp for the EXACT
    ``(project_key, story_id, run_id, signal_type)`` tuple.  ``payload_json``
    is a ``TEXT`` column, so it is cast to ``jsonb`` before the ``->>``
    operator (``(payload_json::jsonb)->>'signal_type' = ?``, NOT LIKE) to
    avoid false matches on substring keys.  Returns the raw ISO-8601 string
    from the DB (``occurred_at`` column), or ``None`` when no matching row
    exists.

    Args:
        story_dir: Unused for Postgres (connection is derived from env); kept
            for API parity with the SQLite driver (FK-35 §35.3.11 / FIX B).
        project_key: Exact project scope.
        story_id: Exact story scope.
        run_id: Exact run scope.
        payload_signal_type: Exact ``signal_type`` value to match in the payload JSON.

    Returns:
        ISO-8601 ``occurred_at`` string of the most-recent matching adjudication,
        or ``None`` when absent.
    """
    del story_dir  # unused — Postgres derives connection from env
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT MAX(occurred_at) AS max_occurred_at
            FROM execution_events
            WHERE project_key = ?
              AND story_id = ?
              AND run_id = ?
              AND event_type = 'governance_adjudication'
              AND (payload_json::jsonb)->>'signal_type' = ?
            """,
            (project_key, story_id, run_id, payload_signal_type),
        ).fetchone()
    if row is None:
        return None
    value = row.get("max_occurred_at") if isinstance(row, dict) else None
    return str(value) if value is not None else None


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
                worktree_roots_json, binding_version, updated_at,
                status, revocation_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE SET
                project_key = EXCLUDED.project_key,
                story_id = EXCLUDED.story_id,
                run_id = EXCLUDED.run_id,
                principal_type = EXCLUDED.principal_type,
                worktree_roots_json = EXCLUDED.worktree_roots_json,
                binding_version = EXCLUDED.binding_version,
                updated_at = EXCLUDED.updated_at,
                status = EXCLUDED.status,
                revocation_reason = EXCLUDED.revocation_reason
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
                row.get("status", "active"),
                row.get("revocation_reason"),
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
# RunOwnershipRecord rows (AG3-137, Postgres-only K5)
# ---------------------------------------------------------------------------


def insert_run_ownership_record_global_row(row: dict[str, Any]) -> None:
    """Strictly INSERT one run-ownership row (AG3-137).

    A plain ``INSERT`` (no ``ON CONFLICT``): a duplicate identity
    ``(project_key, story_id, run_id)`` OR a second ``status='active'`` row for
    the same ``(project_key, story_id)`` fails deterministically with a
    constraint violation (the primary key resp. the
    ``run_ownership_records_active_uidx`` partial-unique index). There is no
    silent overwrite and no application-side check — the persistence layer is the
    single enforcer of ``at_most_one_active_ownership_per_story`` (FK-56 §56.8a,
    AK1). The idempotent backfill uses its own ``ON CONFLICT DO NOTHING`` path.

    Raises:
        psycopg.errors.UniqueViolation: On a duplicate identity or a second
            active ownership record for the same story (fail-closed).
    """

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO run_ownership_records (
                project_key, story_id, run_id, owner_session_id,
                ownership_epoch, status, acquired_via, acquired_at, audit_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["owner_session_id"],
                row["ownership_epoch"],
                row["status"],
                row["acquired_via"],
                row["acquired_at"],
                row["audit_ref"],
            ),
        )


def load_run_ownership_record_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
) -> dict[str, Any] | None:
    """Return the raw run-ownership row for one run identity, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM run_ownership_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
            """,
            (project_key, story_id, run_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def load_active_run_ownership_record_global_row(
    project_key: str,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the raw ACTIVE run-ownership row for a story, or None.

    At most one active row can exist per ``(project_key, story_id)``
    (partial-unique), so this returns a single row.
    """

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM run_ownership_records
            WHERE project_key = ? AND story_id = ? AND status = 'active'
            """,
            (project_key, story_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# ObjectMutationClaimRecord rows (AG3-137, Postgres-only K5)
# ---------------------------------------------------------------------------


def insert_object_mutation_claim_global_row(row: dict[str, Any]) -> None:
    """Strictly INSERT one object-mutation-claim row (AG3-137).

    Plain ``INSERT``: a duplicate identity
    ``(project_key, serialization_scope, scope_key)`` fails deterministically
    with a primary-key violation (AK2, the claimed object is exclusive). The
    productive claim-acquisition / queue logic is AG3-141.

    Raises:
        psycopg.errors.UniqueViolation: On a duplicate claimed object.
    """

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO object_mutation_claims (
                project_key, serialization_scope, scope_key, op_id,
                backend_instance_id, instance_incarnation, acquired_at,
                queue_position
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["project_key"],
                row["serialization_scope"],
                row["scope_key"],
                row["op_id"],
                row["backend_instance_id"],
                row["instance_incarnation"],
                row["acquired_at"],
                row["queue_position"],
            ),
        )


def load_object_mutation_claim_global_row(
    project_key: str,
    serialization_scope: str,
    scope_key: str,
) -> dict[str, Any] | None:
    """Return the raw object-mutation-claim row for one object, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM object_mutation_claims
            WHERE project_key = ? AND serialization_scope = ? AND scope_key = ?
            """,
            (project_key, serialization_scope, scope_key),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def acquire_object_mutation_claim_global_row(row: dict[str, Any]) -> bool:
    """Atomically acquire the per-Story object-mutation claim (AG3-141).

    Serialization is PER MUTATED OBJECT = the Story (FK-91 §91.1a Rule 13,
    default ``(project_key, story_id)``): two mutations of the SAME Story
    collide on the ``object_mutation_claims`` primary key
    ``(project_key, serialization_scope, scope_key)``. A single
    ``INSERT ... ON CONFLICT DO NOTHING`` on that PK IS the serialization --
    exactly one caller inserts (wins); a conflict is the busy/409 case. The PK
    collision is atomic, so no advisory lock and no read-then-write window is
    needed.

    The project-scope / multi-object lock-set / cross-scope fairness /
    ``queue_position`` apparatus was REMOVED as speculative (PO decision, two
    independent reviews): it had no genuine requirement. Project-wide mutations
    (mode-lock, story-number) are single-transaction and stay xact-locked
    (FK-10 §10.5.4). ``queue_position`` is a vestigial
    ``state-storage.entity.object-mutation-claim`` attribute (AG3-137 column)
    with no ordering role here -- it is stamped as a constant ``0``.

    Returns:
        ``True`` iff THIS call now holds the claim; ``False`` when the Story
        object is already claimed by another in-flight mutation -- the caller
        surfaces the deterministic 409 + Retry-After (K4, IMPL-016), never a
        blocking wait.
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            INSERT INTO object_mutation_claims (
                project_key, serialization_scope, scope_key, op_id,
                backend_instance_id, instance_incarnation, acquired_at,
                queue_position
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT (project_key, serialization_scope, scope_key) DO NOTHING
            """,
            (
                row["project_key"],
                row["serialization_scope"],
                row["scope_key"],
                row["op_id"],
                row["backend_instance_id"],
                row["instance_incarnation"],
                row["acquired_at"],
            ),
        )
        #: rowcount == 1 -> THIS caller inserted the claim row (won). rowcount
        #: == 0 -> the object PK already exists (another mutation holds the
        #: Story) -> busy/409. The PK collision IS the serialization.
        return int(cursor.rowcount) == 1


def delete_object_mutation_claim_global(
    project_key: str,
    serialization_scope: str,
    scope_key: str,
    op_id: str,
) -> bool:
    """Ownership-scoped (op_id-CAS) release of one object-mutation claim (AG3-141).

    Deletes the row ONLY when it is still held by *op_id* -- never an
    unconditional delete: a late/duplicate release call after a concurrent
    admin-abort or startup reconciliation already freed the claim (or after a
    DIFFERENT operation has since acquired the same object) is a safe no-op,
    never touching a foreign holder's claim.

    Returns:
        ``True`` iff a row matching ALL of ``(project_key,
        serialization_scope, scope_key, op_id)`` was deleted.
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            DELETE FROM object_mutation_claims
            WHERE project_key = ? AND serialization_scope = ? AND scope_key = ?
              AND op_id = ?
            """,
            (project_key, serialization_scope, scope_key, op_id),
        )
        return int(cursor.rowcount) == 1


def list_orphaned_object_mutation_claims_global_row(
    *,
    backend_instance_id: str,
    before_incarnation: int,
) -> list[dict[str, Any]]:
    """Return object-mutation claims orphaned by EARLIER incarnations of THIS instance.

    Startup reconciliation (AG3-141 Scope item 7, extending the AG3-138
    reconcile scan; ``orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort``):
    a DIRECT scan of ``object_mutation_claims`` (mirrors
    :func:`list_orphaned_claimed_control_plane_operations_global_row` exactly)
    -- independent of whatever happened to the claim's owning
    ``control_plane_operations`` row, so a crash between the durable
    object-claim acquire and the owning operation's own finalize is caught
    even in an edge case where the two rows' lifecycles have diverged (e.g. an
    administrative unconditional delete of the operation row). Claims carrying
    a FOREIGN ``backend_instance_id`` are never returned -- fail-closed, no
    "generous" cleanup of un-attributable claims.
    """

    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT * FROM object_mutation_claims
            WHERE backend_instance_id = ?
              AND instance_incarnation < ?
            ORDER BY project_key, serialization_scope, scope_key
            """,
            (backend_instance_id, before_incarnation),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# TakeoverTransferRecord rows (AG3-137, Postgres-only K5)
# ---------------------------------------------------------------------------


def save_takeover_transfer_record_global_row(row: dict[str, Any]) -> None:
    """Upsert one takeover-transfer row, keyed per participating repo (AG3-137).

    Identity is ``(project_key, story_id, run_id, ownership_epoch, repo_id)`` —
    one row per repo (state-storage v5). Upsert so the productive writer AG3-148
    can materialise the attributes across the challenge → confirm lifecycle.
    """

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO takeover_transfer_records (
                project_key, story_id, run_id, ownership_epoch, repo_id,
                takeover_base_sha, last_push_at, push_lag_hint, base_quality,
                challenge_ref, confirm_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (project_key, story_id, run_id, ownership_epoch, repo_id)
            DO UPDATE SET
                takeover_base_sha = EXCLUDED.takeover_base_sha,
                last_push_at = EXCLUDED.last_push_at,
                push_lag_hint = EXCLUDED.push_lag_hint,
                base_quality = EXCLUDED.base_quality,
                challenge_ref = EXCLUDED.challenge_ref,
                confirm_ref = EXCLUDED.confirm_ref
            """,
            (
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["ownership_epoch"],
                row["repo_id"],
                row.get("takeover_base_sha"),
                row.get("last_push_at"),
                row.get("push_lag_hint"),
                row.get("base_quality"),
                row.get("challenge_ref"),
                row.get("confirm_ref"),
            ),
        )


def load_takeover_transfer_record_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
    ownership_epoch: int,
    repo_id: str,
) -> dict[str, Any] | None:
    """Return the raw takeover-transfer row for one repo identity, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM takeover_transfer_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
            AND ownership_epoch = ? AND repo_id = ?
            """,
            (project_key, story_id, run_id, ownership_epoch, repo_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# BackendInstanceIdentityRecord rows (AG3-137, Postgres-only K5)
# ---------------------------------------------------------------------------


def save_backend_instance_identity_global_row(row: dict[str, Any]) -> None:
    """Upsert the persistent backend-instance-identity row (AG3-137, IMPL-004)."""

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO backend_instance_identity (
                backend_instance_id, instance_incarnation, updated_at
            ) VALUES (?, ?, ?)
            ON CONFLICT (backend_instance_id) DO UPDATE SET
                instance_incarnation = EXCLUDED.instance_incarnation,
                updated_at = EXCLUDED.updated_at
            """,
            (
                row["backend_instance_id"],
                row["instance_incarnation"],
                row["updated_at"],
            ),
        )


def load_backend_instance_identity_global_row(
    backend_instance_id: str,
) -> dict[str, Any] | None:
    """Return the raw backend-instance-identity row, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM backend_instance_identity
            WHERE backend_instance_id = ?
            """,
            (backend_instance_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


#: Advisory-lock key for the boot-time instance-identity resolution (AG3-138).
#: Serializes the read-generate/increment-write sequence against a concurrent
#: boot of the same database (defense in depth; the normative operating
#: assumption is a single active writer instance, FK-10 §10.5.4).
_BACKEND_INSTANCE_IDENTITY_BOOT_LOCK_KEY = "agentkit_backend_instance_identity_boot"


class BackendInstanceIdentitySingletonError(RuntimeError):
    """Raised when ``backend_instance_identity`` unexpectedly holds >1 row.

    The table is a per-installation singleton (AG3-137 schema, AG3-138 boot
    logic): exactly zero or one row is ever written. Finding more than one is a
    schema-invariant violation -- fail-closed rather than guessing which row is
    "the" installation identity.
    """


def boot_backend_instance_identity_global_row(
    *,
    candidate_backend_instance_id: str,
    now: str,
) -> dict[str, Any]:
    """Atomically resolve the boot-time backend instance identity (AG3-138, IMPL-004).

    Under an advisory transaction lock (serialized against a concurrent boot of
    the same database): reads the (at most one) existing
    ``backend_instance_identity`` row.

    * No row exists yet -- this is the FIRST boot ever for this installation:
      insert ``candidate_backend_instance_id`` with ``instance_incarnation = 1``.
    * A row exists -- ``backend_instance_id`` is STABLE across restarts (AC3):
      the EXISTING id is kept unchanged and ``instance_incarnation`` is
      incremented by exactly 1 (monotone, deterministic, no wall-clock input).

    Args:
        candidate_backend_instance_id: The id to use ONLY on a genuine first
            boot (a fresh, unused identity generated by the caller, e.g. a
            uuid4 hex string). Ignored when an installation identity already
            exists.
        now: The ``updated_at`` instant to stamp (ISO-8601 TEXT), matching the
            table's other instant columns.

    Returns:
        The resulting raw row (the stable ``backend_instance_id`` and the new
        ``instance_incarnation``).

    Raises:
        BackendInstanceIdentitySingletonError: When the table unexpectedly
            holds more than one row (schema-invariant violation).
    """

    with _connect_global() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (_BACKEND_INSTANCE_IDENTITY_BOOT_LOCK_KEY,),
        )
        rows = conn.execute(
            "SELECT * FROM backend_instance_identity LIMIT 2",
        ).fetchall()
        if len(rows) > 1:
            raise BackendInstanceIdentitySingletonError(
                "backend_instance_identity holds more than one row; the table "
                "is a per-installation singleton (AG3-137/AG3-138) -- refusing "
                "to guess which row is the installation identity (fail-closed).",
            )
        if not rows:
            conn.execute(
                """
                INSERT INTO backend_instance_identity (
                    backend_instance_id, instance_incarnation, updated_at
                ) VALUES (?, ?, ?)
                """,
                (candidate_backend_instance_id, 1, now),
            )
            return {
                "backend_instance_id": candidate_backend_instance_id,
                "instance_incarnation": 1,
                "updated_at": now,
            }
        existing = dict(rows[0])
        next_incarnation = int(existing["instance_incarnation"]) + 1
        conn.execute(
            """
            UPDATE backend_instance_identity
            SET instance_incarnation = ?, updated_at = ?
            WHERE backend_instance_id = ?
            """,
            (next_incarnation, now, existing["backend_instance_id"]),
        )
        return {
            "backend_instance_id": existing["backend_instance_id"],
            "instance_incarnation": next_incarnation,
            "updated_at": now,
        }


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
    row whose ``status='claimed'`` (a live, owned claim). Only the owner's
    ownership-scoped finalize/release may transition a claimed row. So a
    ``complete_phase`` / ``fail_phase`` (or any non-owner save) reusing a live
    ``start_phase`` op_id can no longer overwrite the claimed row and steal/destroy
    its ownership. The collision is surfaced fail-closed via
    :class:`ControlPlaneClaimCollisionError` (NO ERROR BYPASSING -- it is never a
    silent no-op). A fresh insert and an update of a TERMINAL (non-claimed) row are
    unaffected.

    Raises:
        ControlPlaneClaimCollisionError: When the row already exists and is still
            ``claimed`` (the upsert would have clobbered a live claim).
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            INSERT INTO control_plane_operations (
                op_id, project_key, story_id, run_id, session_id,
                operation_kind, phase, status, response_json,
                created_at, updated_at, claimed_by, claimed_at,
                operation_epoch, backend_instance_id, instance_incarnation,
                declared_serialization_scope, finalized_at, request_body_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                claimed_at = EXCLUDED.claimed_at,
                operation_epoch = EXCLUDED.operation_epoch,
                backend_instance_id = EXCLUDED.backend_instance_id,
                instance_incarnation = EXCLUDED.instance_incarnation,
                declared_serialization_scope =
                    EXCLUDED.declared_serialization_scope,
                finalized_at = EXCLUDED.finalized_at,
                request_body_hash = EXCLUDED.request_body_hash
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
                row.get("operation_epoch"),
                row.get("backend_instance_id"),
                row.get("instance_incarnation"),
                row.get("declared_serialization_scope"),
                row.get("finalized_at"),
                # AG3-140: carry the body-hash on the terminal upsert too.
                row.get("request_body_hash"),
            ),
        )
        # rowcount == 1 on a fresh insert or a qualifying (non-claimed) update;
        # rowcount == 0 ONLY when the conflicting row is still ``claimed`` and the
        # WHERE blocked the overwrite. Fail-closed: a live claimed row was hit.
        if int(cursor.rowcount) == 0:
            raise ControlPlaneClaimCollisionError(
                "control-plane operation save refused: op_id "
                f"{row['op_id']!r} is held by a LIVE 'claimed' row; only the "
                "owner's finalize/release may transition it. A non-owner save "
                "(e.g. complete/fail reusing a live start's op_id) must not "
                "clobber the claim (AG3-054 ERROR-3, fail-closed).",
            )


def claim_control_plane_operation_global_row(row: dict[str, Any]) -> bool:
    """Atomically claim an op_id, inserting only if absent (AG3-054 owner-scoped claim).

    Performs a single ``INSERT ... ON CONFLICT (op_id) DO NOTHING`` with
    ``status='claimed'`` and the per-call ``claimed_by`` / ``claimed_at`` stamp, so
    exactly ONE concurrent caller wins the claim for a given ``op_id``; the loser
    sees zero affected rows and must inspect the row (terminal => replay, a
    foreign claim of ANY age => in-flight rejection; AG3-139: never a CAS
    takeover). The claim happens BEFORE dispatch, so a loser never dispatches.

    AG3-138 (``inflight-operation-record``, FK-91 §91.1a rule 16): the fresh
    ``claimed`` placeholder additionally stamps ``operation_epoch``,
    ``backend_instance_id``, ``instance_incarnation`` and
    ``declared_serialization_scope`` -- every newly-acquired claim carries the
    caller's instance identity and its initial fencing epoch. AG3-139: a foreign
    ``claimed`` row is NEVER taken over here (no CAS takeover exists anymore) --
    a loser always gets the fail-closed in-flight rejection; these columns are
    re-stamped only on a genuinely fresh claim (a new op_id, or one released /
    ended via admin-abort / startup reconciliation).

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
                created_at, updated_at, claimed_by, claimed_at,
                operation_epoch, backend_instance_id, instance_incarnation,
                declared_serialization_scope, request_body_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                row.get("operation_epoch"),
                row.get("backend_instance_id"),
                row.get("instance_incarnation"),
                row.get("declared_serialization_scope"),
                # AG3-140: stamp the request body-hash on the claim so a later
                # claim-loser can decide replay vs idempotency_mismatch.
                row.get("request_body_hash"),
            ),
        )
        return int(cursor.rowcount) == 1


def finalize_control_plane_operation_global_row(
    row: dict[str, Any],
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
    owner_operation_epoch: int | None = None,
) -> bool:
    """Ownership-scoped terminal write of a claimed op (AG3-054 owner-scoped claim).

    Writes the terminal status + response_json and CLEARS ``claimed_by`` ONLY when
    the row is still ``claimed`` by ``owner_token``. If another owner finalized the
    claim, or an admin-abort ended it, in between, the CAS affects zero rows and
    this caller must NOT overwrite the foreign/terminal row -- it returns
    ``False`` so the runtime surfaces a replay/rejection instead.

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW claim instant the owner
    stamped) is given, the CAS also matches ``claimed_at`` (raw column) so it
    scopes to THIS claim generation -- a reused stale owner token (DI/test
    wiring) cannot match a NEWER claim. ``None`` keeps the legacy owner-only CAS.

    AG3-138 (``operation_finalize_requires_cas_on_operation_epoch``): when
    ``owner_operation_epoch`` is given, the CAS additionally requires the stored
    ``operation_epoch`` to be UNCHANGED. An ``admin_abort_inflight_operation``
    bumps the epoch on abort, so a late executor's finalize -- even one whose
    ``owner_token``/``claimed_at`` would otherwise still match -- fails this
    fence deterministically and writes nothing (at most a no-op).

    Returns:
        ``True`` iff this owner's terminal write applied (rowcount == 1).
    """

    epoch_clause, epoch_params = _owner_fencing_cas_clause(
        owner_claimed_at, owner_operation_epoch
    )
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
    """Build the optional claim-generation CAS fragment (AG3-054 WARNING-4, #4).

    When ``owner_claimed_at`` is given, returns a SQL fragment matching the RAW
    ``claimed_at`` column plus its bind parameter, so the ownership CAS scopes to
    THIS claim generation. When ``None`` (legacy administrative callers), returns
    an empty fragment so the CAS stays owner-only (backward compatible). The
    fragment is a fixed string with NO interpolated user data.
    """
    if owner_claimed_at is None:
        return "", ()
    return "\n              AND claimed_at IS NOT DISTINCT FROM ?", (owner_claimed_at,)


def _owner_fencing_cas_clause(
    owner_claimed_at: str | None,
    owner_operation_epoch: int | None,
) -> tuple[str, tuple[str | int, ...]]:
    """Build the optional claim-generation AND operation-epoch CAS fragment (AG3-138).

    Combines the AG3-054 raw-``claimed_at`` claim-generation fence with the
    AG3-138 ``operation_epoch`` fence
    (``operation_finalize_requires_cas_on_operation_epoch``). Either, both or
    neither may be given; each present value adds its own ``AND`` predicate.
    Fixed fragment text, no interpolated user data.
    """
    claim_clause, claim_params = _owner_epoch_cas_clause(owner_claimed_at)
    if owner_operation_epoch is None:
        return claim_clause, claim_params
    epoch_clause = claim_clause + "\n              AND operation_epoch = ?"
    return epoch_clause, (*claim_params, owner_operation_epoch)


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
            worktree_roots_json, binding_version, updated_at,
            status, revocation_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (session_id) DO UPDATE SET
            principal_type = EXCLUDED.principal_type,
            worktree_roots_json = EXCLUDED.worktree_roots_json,
            binding_version = EXCLUDED.binding_version,
            updated_at = EXCLUDED.updated_at,
            -- AG3-137 (Codex WARNING §5b): carry status / revocation_reason on a
            -- same-run rebind too, so an update never leaves a stale status or a
            -- stale reason behind (the mapper always supplies both).
            status = EXCLUDED.status,
            revocation_reason = EXCLUDED.revocation_reason
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
            row["status"],
            row["revocation_reason"],
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
    owner_operation_epoch: int | None = None,
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
    * rowcount == 0 -> the claim was already resolved by a concurrent process (a
      slow owner's own later finalize, or an admin-abort, AG3-138): NOTHING is
      materialized and the transaction is rolled back (the ``with`` block raises
      before commit), so the loser writes NO duplicate/conflicting binding / lock
      / event. The runtime then surfaces the winner's terminal row as a replay.

    The loser therefore never writes canonical side effects -- materialization is
    ownership-gated and atomic with the finalize (FK-22 §22.9, FK-91).

    Args:
        op_row: The terminal control-plane operation row (committed result).
        owner_token: This caller's owner token (the CAS scope).
        owner_claimed_at: This caller's RAW claim instant; when given, the ownership
            CAS also matches ``claimed_at`` so it scopes to THIS claim generation
            (WARNING-4, #4). ``None`` keeps the legacy owner-only CAS.
        owner_operation_epoch: This caller's observed ``operation_epoch`` (AG3-138,
            ``operation_finalize_requires_cas_on_operation_epoch``); when given,
            the CAS additionally requires the stored epoch to be UNCHANGED, so an
            ``admin_abort_inflight_operation`` bump fences a late executor's
            finalize even when its owner token/claim instant would otherwise still match.
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

    epoch_clause, epoch_params = _owner_fencing_cas_clause(
        owner_claimed_at, owner_operation_epoch
    )
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


def list_orphaned_claimed_control_plane_operations_global_row(
    *,
    backend_instance_id: str,
    before_incarnation: int,
) -> list[dict[str, Any]]:
    """Return claimed operations orphaned by EARLIER incarnations of THIS instance.

    Startup reconciliation (AG3-138, FK-91 §91.1a rule 16 /
    ``orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort``):
    finds ``claimed`` control-plane operations stamped with the CALLING
    instance's own ``backend_instance_id`` from a strictly earlier
    ``instance_incarnation``. Claims carrying a FOREIGN ``backend_instance_id``
    (or ``NULL``, a pre-AG3-137 legacy row with no instance stamp) are never
    returned -- fail-closed, no "generous" cleanup of un-attributable claims.
    """

    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT * FROM control_plane_operations
            WHERE status = 'claimed'
              AND backend_instance_id = ?
              AND instance_incarnation < ?
            ORDER BY op_id
            """,
            (backend_instance_id, before_incarnation),
        ).fetchall()
    return [dict(row) for row in rows]


def finalize_orphaned_control_plane_operation_global_row(
    *,
    op_id: str,
    backend_instance_id: str,
    status: str,
    response_json: str,
    now: str,
    owner_operation_epoch: int,
) -> bool:
    """CAS-finalize one orphaned claim during startup reconciliation (AG3-138).

    Fail-closed identity fence: the CAS matches ``op_id`` AND
    ``status = 'claimed'`` AND ``backend_instance_id = ?`` -- a claim whose
    identity or status changed concurrently is left untouched (returns
    ``False``); a foreign identity can never be matched by this predicate.
    ``operation_epoch`` is bumped (``operation_finalize_requires_cas_on_operation_epoch``)
    and the claim columns are cleared.

    ``owner_operation_epoch`` is MANDATORY (AC4): it fences the finalize on the
    ``operation_epoch`` OBSERVED BY THE ORPHAN SCAN, exactly like the normal
    :func:`finalize_control_plane_operation_global_row` claim-generation fence. If the
    row's ``operation_epoch`` changed between the scan and this finalize (e.g. a
    concurrent admin-abort of the same still-``claimed`` identity bumped it), the
    CAS matches zero rows and this call is a deterministic no-op (returns
    ``False``) instead of stamping a terminal status over a row that already moved
    on. There is deliberately NO identity-only (epoch-less) finalize path: a row
    whose ``operation_epoch`` is ``NULL`` can never satisfy ``operation_epoch = ?``
    for a real integer, so a malformed/legacy ``NULL``-epoch row fails the fence and
    is left untouched (fail-closed) rather than finalized without a CAS.

    Returns:
        ``True`` iff this call's finalize applied (rowcount == 1).
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            UPDATE control_plane_operations
            SET status = ?, response_json = ?, updated_at = ?, finalized_at = ?,
                operation_epoch = operation_epoch + 1,
                claimed_by = NULL, claimed_at = NULL
            WHERE op_id = ?
              AND status = 'claimed'
              AND backend_instance_id = ?
              AND operation_epoch = ?
            """,
            (
                status,
                response_json,
                now,
                now,
                op_id,
                backend_instance_id,
                owner_operation_epoch,
            ),
        )
        return int(cursor.rowcount) == 1


def admin_abort_control_plane_operation_global_row(
    *,
    op_id: str,
    status: str,
    response_json: str,
    now: str,
) -> bool:
    """CAS-abort one in-flight claim via the admin-abort service path (AG3-138).

    Acts on ANY currently-``claimed`` operation regardless of which instance
    stamped it -- an explicit administrative override (FK-91 §91.1a
    ``admin_abort_inflight_operation``, FK-55 §55.5 ``admin_transition``) is by
    construction not scoped to the claim's own owner_token/claim generation. Bumps
    ``operation_epoch`` so a late, physically-still-running executor's
    subsequent finalize fails the epoch fence deterministically (at most a
    no-op abort note; ``operation_finalize_requires_cas_on_operation_epoch``).

    Returns:
        ``True`` iff the abort applied; ``False`` when the row was no longer
        ``claimed`` (already resolved) -- the caller surfaces this as a 409.
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            UPDATE control_plane_operations
            SET status = ?, response_json = ?, updated_at = ?, finalized_at = ?,
                operation_epoch = operation_epoch + 1,
                claimed_by = NULL, claimed_at = NULL
            WHERE op_id = ?
              AND status = 'claimed'
            """,
            (status, response_json, now, now, op_id),
        )
        return int(cursor.rowcount) == 1


def has_engine_writes_since_control_plane_claim_global_row(
    *,
    story_id: str,
    since: str,
) -> bool:
    """Whether the engine persisted partial writes UNDER a specific claim window.

    Deterministic, event-based partial-write detection (AG3-138, IMPL-005): compares
    the ALREADY-RECORDED ``flow_executions.started_at`` / ``phase_states.updated_at``
    against ``since`` (the orphaned/aborted claim's OWN ``claimed_at``) -- never the
    current wall clock. ``control_plane/dispatch.py`` runs
    ``engine.run_phase``/``resume_phase`` (own transactions, per the atomicity note
    in this module) BEFORE the control-plane finalize commits; a persisted value
    at/after ``since`` proves the engine already wrote under the claim now being
    finalized as orphaned/aborted, so it must go to the ``repair`` state, never
    silently ``failed``.

    Soundness axis -- FAIL-CLOSED, not silent. The probe is deliberately biased
    toward ``repair``: it reports a partial write on ANY ``story_id`` engine write
    at/after ``since``. This can NEVER produce a false NEGATIVE (a genuine partial
    write silently routed to ``failed``), which is the dangerous, fail-OPEN
    direction that IMPL-005 forbids ("never silently failed"). A ``run_id`` filter
    is deliberately NOT applied precisely because it WOULD introduce false
    negatives: the engine persists
    ``flow_executions.run_id = EngineRuntimeState.resolve_run_id(ctx)`` -- an
    engine-internal id (a fresh ``uuid4`` seed reused via the story's own
    ``flow_executions`` row), DISTINCT from the control-plane operation ``run_id``
    (the client-supplied ``/story-runs/{run_id}`` path value); filtering by the
    control-plane ``run_id`` would miss the engine's real write. ``phase_states`` is
    a story-keyed singleton with no ``run_id`` column at all, so no per-run binding
    exists for it either.

    Precision axis -- bounded, recoverable, AG3-141-dependent. Full precision (no
    false POSITIVE, i.e. no over-conservative ``repair`` for a story whose only
    post-``since`` engine write actually came from a DIFFERENT, successfully
    committed operation of the same story) requires the ``story-lifecycle``
    at-most-one-active-operation-per-story guarantee, so that any ``story_id`` engine
    write in the claim window provably belongs to THIS operation. That guarantee is
    the durable object-mutation-claim (``state-storage.entity.object-mutation-claim``,
    FK-10 §10.5.4) acquired before dispatch -- and its acquisition is AG3-141's
    charter, NOT wired in the AG3-138 window (``control_plane_operations`` claims are
    keyed by ``op_id`` alone; ``run_ownership_records`` and ``object_mutation_claims``
    exist in the schema but have no dispatch-path writer yet). FK-10 §10.5.1/§10.5.4
    make single-writer-per-story a NORMATIVE operating assumption (sequential
    per-story phase runner, one active control-plane writer instance per DB), under
    which this probe is also precise; the residual imprecision is exactly the window
    in which that normative assumption is violated before AG3-141 durably enforces
    it. A false-positive ``repair`` is never a permanent story deadlock: it is
    productively resolved via the admin-abort repair-resolve path
    (:func:`resolve_repair_control_plane_operation_global_row`, AC10).
    """

    with _connect_global() as conn:
        flow_row = conn.execute(
            """
            SELECT 1 FROM flow_executions
            WHERE story_id = ? AND started_at >= ?
            LIMIT 1
            """,
            (story_id, since),
        ).fetchone()
        if flow_row is not None:
            return True
        phase_row = conn.execute(
            """
            SELECT 1 FROM phase_states
            WHERE story_id = ? AND updated_at >= ?
            LIMIT 1
            """,
            (story_id, since),
        ).fetchone()
        return phase_row is not None


def has_open_repair_control_plane_operation_for_story_global_row(
    *,
    project_key: str,
    story_id: str,
) -> bool:
    """Whether *story_id* has an open (unresolved) reconcile/repair state.

    Backs the AC10 fail-closed mutation lock at the dispatch-/operations-layer.
    "Open" means a stored ``repair``-status control-plane operation exists for
    this story; the repair record itself is the single source of truth for the
    lock (no second, driftable boolean flag). AG3-138 provides the productive
    exit: an audited ``admin_abort`` repair-resolve transitions the operation to
    ``resolved`` (see ``resolve_repair_control_plane_operation_global_row``),
    which clears the lock. AG3-150 later generalizes the lock family
    (``freeze_epoch``); this story builds the story-scoped lock and its resolver.
    """

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM control_plane_operations
            WHERE project_key = ? AND story_id = ? AND status = 'repair'
            LIMIT 1
            """,
            (project_key, story_id),
        ).fetchone()
        return row is not None


def resolve_repair_control_plane_operation_global_row(
    *,
    op_id: str,
    response_json: str,
    now: str,
) -> bool:
    """CAS-resolve one open ``repair`` operation to a terminal ``resolved`` state.

    The productive end-way out of the AC10 mutation lock (AG3-138): once an operator
    has handled the partial engine writes that put the story into ``repair`` (out of
    band), the admin-abort repair-resolve path transitions the ``repair`` row to
    ``resolved``. Because :func:`has_open_repair_control_plane_operation_for_story_global_row`
    keys the story-scoped lock on ``status = 'repair'``, moving the row off ``repair``
    lifts the lock and re-admits mutating operations for the story -- so a ``repair``
    (including an over-conservative one, see
    :func:`has_engine_writes_since_control_plane_claim_global_row`) can never be a
    permanent deadlock.

    Fail-closed CAS: the update matches ``op_id`` AND ``status = 'repair'`` only. A
    row that is not (or is no longer) in ``repair`` -- a live ``claimed`` claim, an
    already-``resolved`` row, or any other terminal status -- is left untouched and
    the caller surfaces the miss as a 409 (never a second/duplicate resolve). The
    ``operation_epoch`` is NOT re-bumped: the row is already terminal (its epoch was
    bumped when it entered ``repair``); this is a bookkeeping close-out of an open
    handling state, not a fence against a still-running executor.

    Returns:
        ``True`` iff this call's resolve applied (rowcount == 1).
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            UPDATE control_plane_operations
            SET status = 'resolved', response_json = ?, updated_at = ?,
                finalized_at = ?
            WHERE op_id = ?
              AND status = 'repair'
            """,
            (response_json, now, now, op_id),
        )
        return int(cursor.rowcount) == 1


def _conditional_upsert_control_plane_op_row(
    conn: _CompatConnection, row: dict[str, Any]
) -> None:
    """Conditionally upsert a terminal op row on an EXISTING connection (ERROR-2).

    Shares the conditional-upsert semantics of
    :func:`save_control_plane_operation_global_row` (it REFUSES to overwrite a row
    that is still ``status='claimed'`` -- a live, owned claim) but runs on a
    CALLER-supplied connection so the op-row write and the mutation's side effects
    commit (or roll back) in ONE transaction. The collision is surfaced via
    :class:`ControlPlaneClaimCollisionError` raised INSIDE the transaction, so the
    enclosing ``with _connect_global()`` block re-raises before ``commit`` and the
    already-issued side-effect statements are rolled back -- no orphan binding /
    lock / event survives a collision (AG3-054 ERROR-2, fail-closed atomicity).

    Raises:
        ControlPlaneClaimCollisionError: When the conflicting row is still
            ``claimed`` (the upsert would have clobbered a live claim).
    """
    cursor = conn.execute(
        """
        INSERT INTO control_plane_operations (
            op_id, project_key, story_id, run_id, session_id,
            operation_kind, phase, status, response_json,
            created_at, updated_at, claimed_by, claimed_at,
            request_body_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            claimed_at = EXCLUDED.claimed_at,
            request_body_hash = EXCLUDED.request_body_hash
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
            # AG3-140 finding 3: the complete/fail/closure terminal upsert (no
            # prior claim placeholder) must persist the body-hash so a later
            # replay can classify replay vs 409 idempotency_mismatch on the real
            # store (mirrors save_control_plane_operation_global_row).
            row.get("request_body_hash"),
        ),
    )
    if int(cursor.rowcount) == 0:
        raise ControlPlaneClaimCollisionError(
            "control-plane operation save refused: op_id "
            f"{row['op_id']!r} is held by a LIVE 'claimed' row; only the "
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
    when it would clobber a LIVE ``claimed`` start claim. By then the side effects
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
            ``claimed`` row (nothing is committed; the live claim is intact).
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
    """Ownership-scoped release of a claimed op (AG3-054 owner-scoped claim).

    Deletes the row ONLY when it is still ``claimed`` by ``owner_token``. NEVER an
    unconditional delete: a terminal row (``status != 'claimed'``) and another
    owner's claim are both left untouched, so a release on the exception/rejection
    path can never delete a foreign or committed result. Idempotent.

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW claim instant the owner
    stamped) is given, the delete CAS also matches ``claimed_at`` so it scopes to
    THIS claim generation -- a stale owner (a reused token in DI/test wiring)
    cannot delete a NEWER claim. ``None`` keeps the legacy owner-only CAS.
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
                reason, created_at, consumed_at, check_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(override_id) DO UPDATE SET
                target_node_id=excluded.target_node_id,
                override_type=excluded.override_type,
                actor_type=excluded.actor_type,
                actor_id=excluded.actor_id,
                reason=excluded.reason,
                created_at=excluded.created_at,
                consumed_at=excluded.consumed_at,
                check_id=excluded.check_id
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
                row.get("check_id"),
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
# Runtime-Execution per-owner purge rows (AG3-109)
# ---------------------------------------------------------------------------
#
# Postgres mirror of ``sqlite_store`` purge helpers. The physical §1.3 mapping
# (code is ground truth; FK-18/FK-53 prose drift is a doc-only follow-up) is
# documented in ``sqlite_store``. ``?`` placeholders are translated to ``%s`` by
# ``_CompatConnection``, so the SQL is byte-for-byte the same across both stores.
# Idempotent per FK-53 §53.9.1: delete-if-present, zero when already gone, hard
# fail only on real infra/permission errors. NEVER reference phantom tables
# ``attempt_records`` / ``node_executions`` / ``artifact_records``. The read-model
# ``phase_state_projection`` is OUT OF SCOPE.


def purge_flow_executions_row(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete flow_executions rows for (project_key, story_id, run_id)."""

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM flow_executions "
            "WHERE project_key = ? AND story_id = ? AND run_id = ?",
            (project_key, story_id, run_id),
        )
        return int(cursor.rowcount)


def purge_node_execution_ledgers_row(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete node_execution_ledgers rows for (project_key, story_id, run_id)."""

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM node_execution_ledgers "
            "WHERE project_key = ? AND story_id = ? AND run_id = ?",
            (project_key, story_id, run_id),
        )
        return int(cursor.rowcount)


def purge_attempts_row(
    story_dir: Path,
    story_id: str,
    run_id: str,
) -> int:
    """Delete attempts rows for (story_id, run_id) (no project_key column)."""

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM attempts WHERE story_id = ? AND run_id = ?",
            (story_id, run_id),
        )
        return int(cursor.rowcount)


def purge_override_records_row(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete override_records rows for (project_key, story_id, run_id)."""

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM override_records "
            "WHERE project_key = ? AND story_id = ? AND run_id = ?",
            (project_key, story_id, run_id),
        )
        return int(cursor.rowcount)


def purge_guard_decisions_row(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete guard_decisions rows for (project_key, story_id, run_id)."""

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM guard_decisions "
            "WHERE project_key = ? AND story_id = ? AND run_id = ?",
            (project_key, story_id, run_id),
        )
        return int(cursor.rowcount)


def purge_phase_states_row(
    story_dir: Path,
    story_id: str,
) -> int:
    """Delete the canonical phase_states row for story_id (NOT the projection)."""

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM phase_states WHERE story_id = ?",
            (story_id,),
        )
        return int(cursor.rowcount)


def purge_phase_snapshots_row(
    story_dir: Path,
    story_id: str,
) -> int:
    """Delete all phase_snapshots rows for story_id (every phase).

    Story-keyed runtime PhaseState evidence (second-QA closure, FK-53 §53.7.5
    rule); mirrors the ``sqlite_store`` helper — see its docstring.
    """

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM phase_snapshots WHERE story_id = ?",
            (story_id,),
        )
        return int(cursor.rowcount)


def purge_decision_records_row(
    story_dir: Path,
    story_id: str,
) -> int:
    """Delete all decision_records rows for story_id (every kind/attempt/run).

    Governance runtime residue (second-QA closure, FK-53 §53.7.5 rule): the
    Postgres reader falls back to a story-wide ``MAX(attempt_nr)`` lookup, so a
    purged run's leftover verify decision would shadow the next run's decision.
    Story-keyed delete mirrors the ``sqlite_store`` helper.
    """

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM decision_records WHERE story_id = ?",
            (story_id,),
        )
        return int(cursor.rowcount)


def purge_execution_events_row(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete execution_events rows for (project_key, story_id, run_id)."""

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM execution_events "
            "WHERE project_key = ? AND story_id = ? AND run_id = ?",
            (project_key, story_id, run_id),
        )
        return int(cursor.rowcount)


def purge_run_bound_artifact_envelopes_row(
    story_dir: Path,
    story_id: str,
    run_id: str,
) -> int:
    """Delete run-bound artifact_envelopes rows for (story_id, run_id).

    No ``project_key`` column; every row is bound to ``run_id``. A reset starts a
    new run, so deleting all rows for the OLD ``(story_id, run_id)`` removes the
    run-bound artefacts and leaves other-run rows intact.
    """

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM artifact_envelopes WHERE story_id = ? AND run_id = ?",
            (story_id, run_id),
        )
        return int(cursor.rowcount)


def count_runtime_execution_residue_row(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> dict[str, int]:
    """Count remaining Runtime-Execution rows per table for the run scope.

    Deliberately ``project_key``-agnostic counting (run-bound tables by
    ``(story_id, run_id)``, story-keyed tables by ``story_id``) so a mis-scoped
    purge surfaces as residue — see the ``sqlite_store`` twin's docstring.
    """

    # Residue counting is run-/story-scoped by design — see docstring.
    del project_key
    with _connect(story_dir) as conn:
        return _count_runtime_execution_residue(conn, story_id, run_id)


def _count_runtime_execution_residue(
    conn: _CompatConnection,
    story_id: str,
    run_id: str,
) -> dict[str, int]:
    def _count(sql: str, params: tuple[object, ...]) -> int:
        row = conn.execute(sql, params).fetchone()
        if row is None:
            return 0
        value = next(iter(row.values())) if isinstance(row, dict) else row[0]
        return int(value)

    sr = (story_id, run_id)
    s = (story_id,)
    return {
        "flow_executions": _count(
            "SELECT COUNT(*) AS n FROM flow_executions "
            "WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "node_execution_ledgers": _count(
            "SELECT COUNT(*) AS n FROM node_execution_ledgers "
            "WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "attempts": _count(
            "SELECT COUNT(*) AS n FROM attempts WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "override_records": _count(
            "SELECT COUNT(*) AS n FROM override_records "
            "WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "guard_decisions": _count(
            "SELECT COUNT(*) AS n FROM guard_decisions "
            "WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "decision_records": _count(
            "SELECT COUNT(*) AS n FROM decision_records WHERE story_id = ?",
            s,
        ),
        "phase_states": _count(
            "SELECT COUNT(*) AS n FROM phase_states WHERE story_id = ?",
            s,
        ),
        "phase_snapshots": _count(
            "SELECT COUNT(*) AS n FROM phase_snapshots WHERE story_id = ?",
            s,
        ),
        "execution_events": _count(
            "SELECT COUNT(*) AS n FROM execution_events "
            "WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "artifact_envelopes": _count(
            "SELECT COUNT(*) AS n FROM artifact_envelopes "
            "WHERE story_id = ? AND run_id = ?",
            sr,
        ),
    }


# ---------------------------------------------------------------------------
# Backend predicate helpers (kept as thin wrappers for driver-level checks)
# ---------------------------------------------------------------------------


def backend_has_valid_context(story_dir: Path) -> bool:
    return load_story_context_row(story_dir) is not None


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return load_phase_state_row(story_dir) is not None
