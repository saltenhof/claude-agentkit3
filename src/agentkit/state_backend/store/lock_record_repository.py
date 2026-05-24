"""LockRecordRepository — deactivate story-execution locks in the state backend.

Provides ``deactivate_locks_for_story(story_id)`` which deletes all
``story_execution_locks`` rows for a given story ID and returns the
identifiers of removed records.

This consolidates the lock-deactivation path for ``Governance.deactivate_locks``
without touching the existing ``load_lock`` / ``save_lock`` callables in
``control_plane.repository`` (those remain intact as-is).

Architecture:
- Postgres is canonical (DK-05 §5, FK-60 §60).
- SQLite is a test-only parallel path (``AGENTKIT_ALLOW_SQLITE=1``).
- Does NOT import from ``agentkit.state_backend.store.facade``.
- Direct connection helpers — same pattern as ``governance_hook_repository.py``.

Sources:
- AG3-031 §2.1.2 — lock_record_repository specification
- FK-30 §30.6.0  — Governance.deactivate_locks semantics
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.governance.locks import LockRecordId

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    return os.environ.get("AGENTKIT_STATE_BACKEND", "sqlite").lower() == "postgres"


def _postgres_database_url() -> str:
    url = os.environ.get("AGENTKIT_STATE_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "AGENTKIT_STATE_DATABASE_URL must be set when "
            "AGENTKIT_STATE_BACKEND=postgres"
        )
    return url


# ---------------------------------------------------------------------------
# SQLite helpers (story_execution_locks lives in the same versioned DB)
# ---------------------------------------------------------------------------


def _sqlite_db_path(store_dir: Path) -> Path:
    from agentkit.state_backend.config import versioned_sqlite_db_file
    from agentkit.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_sqlite_lock_schema(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_sqlite_lock_schema(conn: sqlite3.Connection) -> None:
    """Ensure story_execution_locks table exists (idempotent)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS story_execution_locks (
            project_key TEXT NOT NULL,
            story_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            lock_type TEXT NOT NULL,
            status TEXT NOT NULL,
            worktree_roots_json TEXT NOT NULL,
            binding_version TEXT NOT NULL,
            activated_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deactivated_at TEXT,
            PRIMARY KEY (project_key, run_id, lock_type)
        )
        """
    )


# ---------------------------------------------------------------------------
# Postgres helpers
# ---------------------------------------------------------------------------


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row

    from agentkit.state_backend.config import versioned_postgres_schema_name

    schema = versioned_postgres_schema_name()
    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.execute(f"SET search_path TO {schema}, public")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Canonical lock-record key construction
# ---------------------------------------------------------------------------


def _lock_record_id(row: dict[str, Any]) -> LockRecordId:
    """Build a stable ``LockRecordId`` from a raw DB row."""
    return LockRecordId(
        f"{row['project_key']}|{row['story_id']}|{row['run_id']}|{row['lock_type']}"
    )


# ---------------------------------------------------------------------------
# LockRecordRepository
# ---------------------------------------------------------------------------


class LockRecordRepository:
    """Persistence adapter for story-execution lock deactivation.

    This repository adds the ``deactivate_locks_for_story`` surface to the
    existing state-backend without touching the ``control_plane.repository``
    callable approach (``load_lock`` / ``save_lock`` remain intact).

    Args:
        store_dir: Base directory for SQLite state store. Ignored for Postgres.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    def deactivate_locks_for_story(self, story_id: str) -> list[LockRecordId]:
        """Mark all lock records for ``story_id`` as deactivated and return IDs.

        Implementation: UPDATE rows to ``status='DEACTIVATED'`` and set
        ``deactivated_at``, then return the ``LockRecordId`` of each row.
        If no rows exist, returns an empty list (idempotent).

        Args:
            story_id: Canonical story identifier.

        Returns:
            List of ``LockRecordId`` for all deactivated lock records.

        Raises:
            Exception: On unrecoverable backend failures (fail-closed).
        """
        if _is_postgres():
            return self._pg_deactivate(story_id)
        return self._sqlite_deactivate(story_id)

    def _sqlite_deactivate(self, story_id: str) -> list[LockRecordId]:
        now_ts = datetime.now(UTC).isoformat()
        with _sqlite_connect(self._store_dir) as conn:
            # Fetch affected rows first (SQLite UPDATE RETURNING not universal)
            cursor = conn.execute(
                """
                SELECT project_key, story_id, run_id, lock_type
                FROM story_execution_locks
                WHERE story_id = ? AND status != 'DEACTIVATED'
                """,
                (story_id,),
            )
            rows = [dict(row) for row in cursor.fetchall()]

            if rows:
                conn.execute(
                    """
                    UPDATE story_execution_locks
                    SET status = 'DEACTIVATED', deactivated_at = ?
                    WHERE story_id = ? AND status != 'DEACTIVATED'
                    """,
                    (now_ts, story_id),
                )

        return [_lock_record_id(row) for row in rows]

    def _pg_deactivate(self, story_id: str) -> list[LockRecordId]:
        now_ts = datetime.now(UTC).isoformat()
        with _postgres_connect() as conn:
            cursor = conn.execute(
                """
                UPDATE story_execution_locks
                SET status = 'DEACTIVATED', deactivated_at = %s
                WHERE story_id = %s AND status != 'DEACTIVATED'
                RETURNING project_key, story_id, run_id, lock_type
                """,
                (now_ts, story_id),
            )
            rows = cursor.fetchall() or []

        return [_lock_record_id(dict(row)) for row in rows]


__all__ = ["LockRecordRepository"]
