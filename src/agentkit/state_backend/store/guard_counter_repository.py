"""StateBackendGuardCounterRepository — guard-invocation counter scratchpad (AG3-081).

Productive SQLite/Postgres implementation of the consumer-owned
``GuardCounterRepository`` Protocol
(``agentkit.kpi_analytics.fact_store.repository``), backing the FK-61 §61.4.3
hot-path scratchpad ``guard_invocation_counters``. Mirrors
``StateBackendFactRepository``:

- Postgres is the canonical truth; SQLite is the test-parallel path
  (``AGENTKIT_ALLOW_SQLITE=1``). The DDL lives in the canonical schema
  (``postgres_schema.sql`` / ``migration/versions/v_3_4_analytics.sql``); this
  adapter carries no DDL truth.
- The hot-path UPSERT is the FK-61 §61.4.3 statement verbatim
  (``ON CONFLICT ... DO UPDATE SET invocations = invocations + 1,
  blocks = blocks + EXCLUDED.blocks``).
- Fail-closed: a read against a missing table propagates the backend error — never
  a silent empty result.

Architecture Conformance (AC8): the KPI fact-store knows only the
``GuardCounterRepository`` Protocol (defined in ``kpi_analytics.fact_store``); this
adapter is wired in the composition root / at the runner edge.
``kpi_analytics.fact_store`` never imports this module.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.kpi_analytics.fact_store.models import GuardInvocationCounter

if TYPE_CHECKING:
    from collections.abc import Iterator


def _is_postgres() -> bool:
    from agentkit.state_backend.config import (
        StateBackendKind,
        load_state_backend_config,
    )

    return load_state_backend_config().backend is StateBackendKind.POSTGRES


def _assert_sqlite_allowed() -> None:
    from agentkit.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed

    if not _sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for this path. "
            f"Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )


def _postgres_database_url() -> str:
    import os

    url = os.environ.get("AGENTKIT_STATE_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "AGENTKIT_STATE_DATABASE_URL must be set when "
            "AGENTKIT_STATE_BACKEND=postgres"
        )
    return url


def _sqlite_db_path(store_dir: Path) -> Path:
    from agentkit.state_backend.config import versioned_sqlite_db_file
    from agentkit.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    from agentkit.state_backend import sqlite_store

    _assert_sqlite_allowed()
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    sqlite_store._ensure_schema(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row

    from agentkit.state_backend import postgres_store
    from agentkit.state_backend.schema_bootstrap import ensure_versioned_schema

    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        ensure_versioned_schema(conn)
        postgres_store._ensure_schema(postgres_store._CompatConnection(conn))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ts(value: datetime, *, is_postgres: bool) -> Any:
    """Bind ``updated_at`` (TIMESTAMPTZ on Postgres, ISO-8601 TEXT on SQLite)."""
    return value if is_postgres else value.isoformat()


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _row_to_counter(row: dict[str, Any]) -> GuardInvocationCounter:
    return GuardInvocationCounter(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        guard_key=str(row["guard_key"]),
        week_start=str(row["week_start"]),
        invocations=int(row["invocations"]),
        blocks=int(row["blocks"]),
        updated_at=_dt(row["updated_at"]),
    )


class StateBackendGuardCounterRepository:
    """SQLite/Postgres implementation of ``GuardCounterRepository`` (AG3-081).

    Backend selected via ``AGENTKIT_STATE_BACKEND``; Postgres is canonical, SQLite
    is the test-parallel path (``AGENTKIT_ALLOW_SQLITE=1``).

    Args:
        store_dir: Base directory for the SQLite store (Postgres ignores it).
            Default: ``Path.cwd()``.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    def upsert_invocation(
        self,
        *,
        project_key: str,
        story_id: str,
        guard_key: str,
        week_start: str,
        blocked: bool,
        updated_at: datetime,
    ) -> None:
        """UPSERT one guard invocation (FK-61 §61.4.3 statement verbatim)."""
        is_pg = _is_postgres()
        params = {
            "project_key": project_key,
            "story_id": story_id,
            "guard_key": guard_key,
            "week_start": week_start,
            "blocks_inc": 1 if blocked else 0,
            "updated_at": _ts(updated_at, is_postgres=is_pg),
        }
        columns = (
            "project_key, story_id, guard_key, week_start, invocations, blocks, "
            "updated_at"
        )
        update_clause = (
            "invocations = guard_invocation_counters.invocations + 1, "
            "blocks = guard_invocation_counters.blocks + EXCLUDED.blocks, "
            "updated_at = EXCLUDED.updated_at"
        )
        conflict = "project_key, story_id, guard_key, week_start"
        if is_pg:
            statement = (
                f"INSERT INTO guard_invocation_counters ({columns}) "
                "VALUES (%(project_key)s, %(story_id)s, %(guard_key)s, "
                "%(week_start)s, 1, %(blocks_inc)s, %(updated_at)s) "
                f"ON CONFLICT ({conflict}) DO UPDATE SET {update_clause}"
            )
            with _postgres_connect() as conn:
                conn.execute(statement, params)
            return
        statement = (
            f"INSERT INTO guard_invocation_counters ({columns}) "
            "VALUES (:project_key, :story_id, :guard_key, :week_start, 1, "
            ":blocks_inc, :updated_at) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {update_clause}"
        )
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute(statement, params)

    def read_counters_for_story(
        self, project_key: str, story_id: str
    ) -> list[GuardInvocationCounter]:
        """Return all counter rows for ``(project_key, story_id)``."""
        return self._select(
            "SELECT * FROM guard_invocation_counters WHERE project_key = ? "
            "AND story_id = ? ORDER BY guard_key, week_start",
            (project_key, story_id),
        )

    def read_counters_for_story_before_week(
        self, project_key: str, story_id: str, week_start: str
    ) -> list[GuardInvocationCounter]:
        """Return counter rows of older weeks (``week_start < week_start``)."""
        return self._select(
            "SELECT * FROM guard_invocation_counters WHERE project_key = ? "
            "AND story_id = ? AND week_start < ? ORDER BY guard_key, week_start",
            (project_key, story_id, week_start),
        )

    def read_counters_stale(self, cutoff: datetime) -> list[GuardInvocationCounter]:
        """Return counter rows older than ``cutoff`` (by ``updated_at``)."""
        return self._select(
            "SELECT * FROM guard_invocation_counters WHERE updated_at < ? "
            "ORDER BY project_key, story_id, guard_key, week_start",
            (_ts(cutoff, is_postgres=_is_postgres()),),
        )

    def delete_counters_for_story(self, project_key: str, story_id: str) -> int:
        """Delete every counter row for ``(project_key, story_id)``."""
        return self._execute(
            "DELETE FROM guard_invocation_counters WHERE project_key = ? "
            "AND story_id = ?",
            (project_key, story_id),
        )

    def delete_counters_for_story_before_week(
        self, project_key: str, story_id: str, week_start: str
    ) -> int:
        """Delete older-week counter rows (``week_start < week_start``)."""
        return self._execute(
            "DELETE FROM guard_invocation_counters WHERE project_key = ? "
            "AND story_id = ? AND week_start < ?",
            (project_key, story_id, week_start),
        )

    def delete_counters_stale(self, cutoff: datetime) -> int:
        """Delete counter rows older than ``cutoff`` (by ``updated_at``)."""
        return self._execute(
            "DELETE FROM guard_invocation_counters WHERE updated_at < ?",
            (_ts(cutoff, is_postgres=_is_postgres()),),
        )

    # ------------------------------------------------------------------
    # internal engine
    # ------------------------------------------------------------------

    def _select(
        self, query: str, params: tuple[Any, ...]
    ) -> list[GuardInvocationCounter]:
        if _is_postgres():
            with _postgres_connect() as conn:
                rows = conn.execute(query.replace("?", "%s"), params).fetchall()
            return [_row_to_counter(dict(r)) for r in rows]
        with _sqlite_connect(self._store_dir) as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_counter(dict(r)) for r in rows]

    def _execute(self, statement: str, params: tuple[Any, ...]) -> int:
        if _is_postgres():
            with _postgres_connect() as conn:
                cursor = conn.execute(statement.replace("?", "%s"), params)
                return int(cursor.rowcount)
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(statement, params)
            return int(cursor.rowcount)


__all__ = ["StateBackendGuardCounterRepository"]
