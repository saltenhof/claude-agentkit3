"""Canonical project mode-lock and holder-identity persistence."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.backend.governance.errors import ModeLockConflictError

if TYPE_CHECKING:
    from collections.abc import Iterator

ACTIVE_MODE_VALUES: frozenset[str] = frozenset({"standard", "fast"})


@dataclass(frozen=True)
class ModeLockRecord:
    """Project-wide mode-lock summary kept in lockstep with holder rows."""

    project_key: str
    active_mode: str | None
    holder_count: int
    updated_at: str


@dataclass(frozen=True)
class ModeLockHolderRecord:
    """Authoritative identity of one story-run holding a project mode lock."""

    project_key: str
    story_id: str
    run_id: str
    mode: str
    acquired_at: str


class ModeLockRepository:
    """Atomically maintain the lock summary from its authoritative holder set."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def acquire(
        self, project_key: str, story_id: str, run_id: str, mode: str
    ) -> ModeLockRecord:
        """Acquire idempotently for one story-run in a single CAS transaction."""
        _validate_identity(project_key, story_id, run_id, mode)
        if _is_postgres():
            with _postgres_connect() as conn:
                _pg_lock(conn, project_key)
                return _acquire_in_tx(conn, project_key, story_id, run_id, mode)
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute("BEGIN IMMEDIATE")
            return _acquire_in_tx(conn, project_key, story_id, run_id, mode)

    def release(self, project_key: str, story_id: str, run_id: str) -> ModeLockRecord:
        """Release only the commanding story-run's holder in one transaction."""
        _validate_identity(project_key, story_id, run_id)
        if _is_postgres():
            with _postgres_connect() as conn:
                _pg_lock(conn, project_key)
                return _release_in_tx(conn, project_key, story_id, run_id)
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute("BEGIN IMMEDIATE")
            return _release_in_tx(conn, project_key, story_id, run_id)

    def read_lock(self, project_key: str) -> ModeLockRecord | None:
        """Read and verify the summary against the authoritative holder set."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM project_mode_lock WHERE project_key = ?", (project_key,)
            ).fetchone()
            holders = _holder_rows(conn, project_key)
        if row is None:
            if holders:
                raise RuntimeError("mode-lock holders exist without a summary row")
            return None
        record = _lock_record(dict(row))
        mode, count = _holder_summary(holders)
        if (record.active_mode, record.holder_count) != (mode, count):
            raise RuntimeError("project_mode_lock diverges from holder identity set")
        return record

    def read_holder(
        self, project_key: str, story_id: str, run_id: str
    ) -> ModeLockHolderRecord | None:
        """Read the authoritative holder identity for one story-run."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM project_mode_lock_holders WHERE project_key = ? "
                "AND story_id = ? AND run_id = ?", (project_key, story_id, run_id)
            ).fetchone()
        return _holder_record(dict(row)) if row is not None else None

    def list_holders(self, project_key: str) -> tuple[ModeLockHolderRecord, ...]:
        """List authoritative holders for recovery and diagnostics."""
        with self._connect() as conn:
            rows = _holder_rows(conn, project_key)
        return tuple(_holder_record(row) for row in rows)

    def _connect(self) -> Any:
        return _postgres_connect() if _is_postgres() else _sqlite_connect(self._store_dir)


def _acquire_in_tx(
    conn: Any, project_key: str, story_id: str, run_id: str, mode: str
) -> ModeLockRecord:
    now = _now_iso()
    _ensure_summary_row(conn, project_key, now)
    holders = _holder_rows(conn, project_key)
    existing = next(
        (row for row in holders if row["story_id"] == story_id and row["run_id"] == run_id),
        None,
    )
    if existing is not None and existing["mode"] != mode:
        raise ModeLockConflictError("the story-run already holds the opposite mode")
    held_mode, _ = _holder_summary(holders)
    if existing is None and held_mode is not None and held_mode != mode:
        raise ModeLockConflictError(f"project already has active mode {held_mode!r}")
    if existing is None:
        conn.execute(
            "INSERT INTO project_mode_lock_holders "
            "(project_key, story_id, run_id, mode, acquired_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (project_key, story_id, run_id) DO NOTHING",
            (project_key, story_id, run_id, mode, now),
        )
    return _sync_summary(conn, project_key, now)


def _release_in_tx(conn: Any, project_key: str, story_id: str, run_id: str) -> ModeLockRecord:
    now = _now_iso()
    _ensure_summary_row(conn, project_key, now)
    conn.execute(
        "DELETE FROM project_mode_lock_holders WHERE project_key = ? "
        "AND story_id = ? AND run_id = ?", (project_key, story_id, run_id)
    )
    return _sync_summary(conn, project_key, now)


def _sync_summary(conn: Any, project_key: str, now: str) -> ModeLockRecord:
    mode, count = _holder_summary(_holder_rows(conn, project_key))
    conn.execute(
        "UPDATE project_mode_lock SET active_mode = ?, holder_count = ?, updated_at = ? "
        "WHERE project_key = ?", (mode, count, now, project_key)
    )
    return ModeLockRecord(project_key, mode, count, now)


def _ensure_summary_row(conn: Any, project_key: str, now: str) -> None:
    conn.execute(
        "INSERT INTO project_mode_lock (project_key, active_mode, holder_count, updated_at) "
        "VALUES (?, NULL, 0, ?) ON CONFLICT (project_key) DO NOTHING", (project_key, now)
    )


def _holder_rows(conn: Any, project_key: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM project_mode_lock_holders WHERE project_key = ? "
        "ORDER BY story_id, run_id", (project_key,)
    ).fetchall()
    return [dict(row) for row in rows]


def _holder_summary(rows: list[dict[str, Any]]) -> tuple[str | None, int]:
    modes = {str(row["mode"]) for row in rows}
    if len(modes) > 1:
        raise RuntimeError("mode-lock holder set contains conflicting modes")
    return (next(iter(modes)) if modes else None, len(rows))


def _lock_record(row: dict[str, Any]) -> ModeLockRecord:
    return ModeLockRecord(
        str(row["project_key"]), row["active_mode"], int(row["holder_count"]),
        str(row["updated_at"]),
    )


def _holder_record(row: dict[str, Any]) -> ModeLockHolderRecord:
    return ModeLockHolderRecord(
        str(row["project_key"]), str(row["story_id"]), str(row["run_id"]),
        str(row["mode"]), str(row["acquired_at"]),
    )


def _validate_identity(
    project_key: str, story_id: str, run_id: str, mode: str | None = None
) -> None:
    if not project_key or not story_id or not run_id:
        raise ValueError("project_key, story_id and run_id must be non-empty")
    if mode is not None and mode not in ACTIVE_MODE_VALUES:
        raise ValueError(f"mode {mode!r} must be one of {sorted(ACTIVE_MODE_VALUES)}")


def _is_postgres() -> bool:
    return os.environ.get("AGENTKIT_STATE_BACKEND", "sqlite").lower() == "postgres"


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    from agentkit.backend.state_backend import postgres_store
    from agentkit.backend.state_backend.postgres_store._compat import _CompatConnection
    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    with postgres_store.borrow_repository_connection() as conn:
        ensure_versioned_schema(conn)
        yield _CompatConnection(conn)


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    from agentkit.backend.state_backend import sqlite_store
    from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed, versioned_sqlite_db_file
    from agentkit.backend.state_backend.paths import state_backend_dir

    if not _sqlite_allowed():
        raise RuntimeError(f"SQLite mode-lock requires {ALLOW_SQLITE_ENV}=1")
    path = state_backend_dir(store_dir) / versioned_sqlite_db_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        sqlite_store._ensure_schema(conn)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _pg_lock(conn: Any, project_key: str) -> None:
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext(?))", (f"project_mode_lock:{project_key}",)
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "ACTIVE_MODE_VALUES", "ModeLockHolderRecord", "ModeLockRecord", "ModeLockRepository",
]
