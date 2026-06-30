"""State-backend repository for FK-36 story-scoped compaction epochs."""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.backend.boundary.shared.time import now_iso

if TYPE_CHECKING:
    from collections.abc import Iterator


_SQLITE_INIT_LOCKS_GUARD = threading.Lock()
_SQLITE_INIT_LOCKS: dict[Path, threading.Lock] = {}


def _sqlite_init_lock(db_path: Path) -> threading.Lock:
    """Return the process-local initialization lock for a SQLite database."""
    key = db_path.resolve()
    with _SQLITE_INIT_LOCKS_GUARD:
        lock = _SQLITE_INIT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _SQLITE_INIT_LOCKS[key] = lock
        return lock


def _is_postgres() -> bool:
    """Return True when the canonical backend is Postgres."""
    from agentkit.backend.state_backend.config import (
        StateBackendKind,
        load_state_backend_config,
    )

    return load_state_backend_config().backend is StateBackendKind.POSTGRES


def _assert_sqlite_allowed() -> None:
    from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed

    if not _sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for this path. "
            f"Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )


def _postgres_database_url() -> str:
    url = os.environ.get("AGENTKIT_STATE_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "AGENTKIT_STATE_DATABASE_URL must be set when "
            "AGENTKIT_STATE_BACKEND=postgres"
        )
    return url


def _sqlite_db_path(store_dir: Path) -> Path:
    from agentkit.backend.state_backend.config import versioned_sqlite_db_file
    from agentkit.backend.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    from agentkit.backend.state_backend import sqlite_store

    _assert_sqlite_allowed()
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    try:
        # Setup runs inside try so a bootstrap failure closes the conn (no leak).
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        with _sqlite_init_lock(db_path):
            current_mode = conn.execute("PRAGMA journal_mode").fetchone()
            if current_mode is None or str(current_mode[0]).lower() != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
            sqlite_store._ensure_schema(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        conn.close()


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row

    from agentkit.backend.state_backend import postgres_store
    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        ensure_versioned_schema(conn)
        postgres_store._ensure_schema_once(postgres_store._CompatConnection(conn))
        conn.commit()
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class StateBackendCompactionEpochRepository:
    """SQLite/Postgres implementation of the FK-36 epoch repository."""

    def __init__(self, store_dir: Path | None = None) -> None:
        """Create a repository bound to the active state backend."""
        self._store_dir = store_dir or Path.cwd()

    def read_epoch(self, project_key: str, story_id: str) -> int:
        """Return the current epoch for ``(project_key, story_id)``, defaulting to 0."""
        if _is_postgres():
            with _postgres_connect() as conn:
                row = conn.execute(
                    """
                    SELECT epoch FROM compaction_epochs
                    WHERE project_key = %s AND story_id = %s
                    """,
                    (project_key, story_id),
                ).fetchone()
            return 0 if row is None else int(row["epoch"])
        with _sqlite_connect(self._store_dir) as conn:
            row = conn.execute(
                """
                SELECT epoch FROM compaction_epochs
                WHERE project_key = ? AND story_id = ?
                """,
                (project_key, story_id),
            ).fetchone()
        return 0 if row is None else int(row["epoch"])

    def increment_epoch(self, project_key: str, story_id: str) -> int:
        """Atomically increment and return the epoch for ``(project_key, story_id)``."""
        updated_at = now_iso()
        if _is_postgres():
            with _postgres_connect() as conn:
                row = conn.execute(
                    """
                    INSERT INTO compaction_epochs (
                        project_key, story_id, epoch, updated_at
                    ) VALUES (%s, %s, 1, %s)
                    ON CONFLICT (project_key, story_id)
                    DO UPDATE SET
                        epoch = compaction_epochs.epoch + 1,
                        updated_at = EXCLUDED.updated_at
                    RETURNING epoch
                    """,
                    (project_key, story_id, updated_at),
                ).fetchone()
            if row is None:  # pragma: no cover - RETURNING always yields one row
                raise RuntimeError("compaction epoch increment returned no row")
            return int(row["epoch"])
        with _sqlite_connect(self._store_dir) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO compaction_epochs (
                        project_key, story_id, epoch, updated_at
                    ) VALUES (?, ?, 1, ?)
                    ON CONFLICT(project_key, story_id)
                    DO UPDATE SET
                        epoch = compaction_epochs.epoch + 1,
                        updated_at = excluded.updated_at
                    """,
                    (project_key, story_id, updated_at),
                )
                row = conn.execute(
                    """
                    SELECT epoch FROM compaction_epochs
                    WHERE project_key = ? AND story_id = ?
                    """,
                    (project_key, story_id),
                ).fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        if row is None:  # pragma: no cover - transaction just wrote the row
            raise RuntimeError("compaction epoch increment returned no row")
        return int(row["epoch"])


__all__ = ["StateBackendCompactionEpochRepository"]
