"""Conflict-freeze proof persistence repository."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.backend.governance.guard_system.records import ConflictFreezeProofRecord

if TYPE_CHECKING:
    from collections.abc import Iterator


def _is_postgres() -> bool:
    return os.environ.get("AGENTKIT_STATE_BACKEND", "sqlite").lower() == "postgres"


def _assert_sqlite_allowed() -> None:
    from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed

    if not _sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for this path. "
            f"Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )


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
    conn = sqlite3.connect(str(db_path))
    try:
        # Setup runs inside try so a bootstrap failure closes the conn (no leak).
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        sqlite_store._ensure_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    from agentkit.backend.state_backend import postgres_store
    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    with postgres_store.borrow_repository_connection() as conn:
        ensure_versioned_schema(conn)
        yield conn


class ConflictFreezeProofRepository:
    """SQLite/Postgres-backed conflict-freeze proof repository."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def save(self, record: ConflictFreezeProofRecord) -> None:
        """Persist a canonical conflict-freeze proof record."""
        if _is_postgres():
            with _postgres_connect() as conn:
                conn.execute(_PG_INSERT, _to_row(record))
            return
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute(_SQLITE_INSERT, _to_row(record))

    def latest_for_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> ConflictFreezeProofRecord | None:
        """Return the latest proof for the run, if one exists."""
        params = {
            "project_key": project_key,
            "story_id": story_id,
            "run_id": run_id,
        }
        if _is_postgres():
            with _postgres_connect() as conn:
                row = conn.execute(_PG_SELECT, params).fetchone()
        else:
            with _sqlite_connect(self._store_dir) as conn:
                row = conn.execute(_SQLITE_SELECT, params).fetchone()
        return None if row is None else _from_row(dict(row))


_SQLITE_INSERT = """
    INSERT INTO conflict_freeze_proofs (
        project_key, story_id, run_id, proof_id, activated_at,
        blocked_principal, resolution_service_path
    ) VALUES (
        :project_key, :story_id, :run_id, :proof_id, :activated_at,
        :blocked_principal, :resolution_service_path
    )
"""

_PG_INSERT = """
    INSERT INTO conflict_freeze_proofs (
        project_key, story_id, run_id, proof_id, activated_at,
        blocked_principal, resolution_service_path
    ) VALUES (
        %(project_key)s, %(story_id)s, %(run_id)s, %(proof_id)s,
        %(activated_at)s, %(blocked_principal)s, %(resolution_service_path)s
    )
"""

_SQLITE_SELECT = """
    SELECT * FROM conflict_freeze_proofs
    WHERE project_key=:project_key AND story_id=:story_id AND run_id=:run_id
    ORDER BY activated_at DESC, proof_id DESC
    LIMIT 1
"""

_PG_SELECT = """
    SELECT * FROM conflict_freeze_proofs
    WHERE project_key=%(project_key)s AND story_id=%(story_id)s
      AND run_id=%(run_id)s
    ORDER BY activated_at DESC, proof_id DESC
    LIMIT 1
"""


def _to_row(record: ConflictFreezeProofRecord) -> dict[str, object]:
    return {
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "proof_id": record.proof_id,
        "activated_at": record.activated_at.isoformat(),
        "blocked_principal": record.blocked_principal,
        "resolution_service_path": record.resolution_service_path,
    }


def _from_row(row: dict[str, Any]) -> ConflictFreezeProofRecord:
    return ConflictFreezeProofRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        proof_id=str(row["proof_id"]),
        activated_at=datetime.fromisoformat(str(row["activated_at"])),
        blocked_principal=str(row["blocked_principal"]),
        resolution_service_path=str(row["resolution_service_path"]),
    )


__all__ = ["ConflictFreezeProofRepository"]
