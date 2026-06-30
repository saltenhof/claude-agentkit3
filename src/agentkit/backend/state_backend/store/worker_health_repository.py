"""State-backend repository for worker-health state."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from agentkit.backend.implementation.worker_health.models import AgentHealthState

if TYPE_CHECKING:
    from collections.abc import Iterator


class WorkerHealthStateRepository(Protocol):
    """Repository protocol for the authoritative worker-health state."""

    def save(self, state: AgentHealthState) -> None: ...

    def load(self, *, story_id: str, worker_id: str) -> AgentHealthState | None: ...

    def load_latest_for_story(self, story_id: str) -> AgentHealthState | None: ...

    def list_for_story(self, story_id: str) -> list[AgentHealthState]: ...


def _is_postgres() -> bool:
    return os.environ.get("AGENTKIT_STATE_BACKEND", "sqlite").lower() == "postgres"


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
            "AGENTKIT_STATE_DATABASE_URL must be set when AGENTKIT_STATE_BACKEND=postgres"
        )
    return url


def _dump_state(state: AgentHealthState) -> str:
    return state.model_dump_json()


def _load_state(payload: str) -> AgentHealthState:
    return AgentHealthState.model_validate_json(payload)


_CREATE_SQLITE = """
CREATE TABLE IF NOT EXISTS worker_health_states (
    story_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    project_key TEXT NOT NULL,
    run_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (story_id, worker_id)
);
CREATE INDEX IF NOT EXISTS worker_health_states_story_updated_idx
    ON worker_health_states (story_id, updated_at);
"""

_CREATE_POSTGRES = """
CREATE TABLE IF NOT EXISTS worker_health_states (
    story_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    project_key TEXT NOT NULL,
    run_id TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (story_id, worker_id)
);
CREATE INDEX IF NOT EXISTS worker_health_states_story_updated_idx
    ON worker_health_states (story_id, updated_at);
"""


def _sqlite_db_path(store_dir: Path) -> Path:
    from agentkit.backend.state_backend.config import versioned_sqlite_db_file
    from agentkit.backend.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    _assert_sqlite_allowed()
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        # Setup runs inside try so a bootstrap failure closes the conn (no leak).
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_CREATE_SQLITE)
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

    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        ensure_versioned_schema(conn)
        conn.execute(_CREATE_POSTGRES)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class StateBackendWorkerHealthRepository:
    """SQLite/Postgres-backed worker-health state repository."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def save(self, state: AgentHealthState) -> None:
        """Persist one worker-health state."""

        if _is_postgres():
            self._pg_save(state)
        else:
            self._sqlite_save(state)

    def load(self, *, story_id: str, worker_id: str) -> AgentHealthState | None:
        """Load one worker-health state."""

        if _is_postgres():
            return self._pg_load(story_id=story_id, worker_id=worker_id)
        return self._sqlite_load(story_id=story_id, worker_id=worker_id)

    def load_latest_for_story(self, story_id: str) -> AgentHealthState | None:
        """Load the latest updated worker-health state for a story."""

        states = self.list_for_story(story_id)
        return states[0] if states else None

    def list_for_story(self, story_id: str) -> list[AgentHealthState]:
        """List worker-health states for a story, newest first."""

        if _is_postgres():
            return self._pg_list_for_story(story_id)
        return self._sqlite_list_for_story(story_id)

    def _sqlite_save(self, state: AgentHealthState) -> None:
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute(
                """
                INSERT INTO worker_health_states
                    (story_id, worker_id, project_key, run_id, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(story_id, worker_id) DO UPDATE SET
                    project_key = excluded.project_key,
                    run_id = excluded.run_id,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    state.story_id,
                    state.worker_id,
                    state.project_key,
                    state.run_id,
                    _dump_state(state),
                    state.last_updated.isoformat(),
                ),
            )

    def _sqlite_load(
        self,
        *,
        story_id: str,
        worker_id: str,
    ) -> AgentHealthState | None:
        with _sqlite_connect(self._store_dir) as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM worker_health_states
                WHERE story_id = ? AND worker_id = ?
                """,
                (story_id, worker_id),
            ).fetchone()
        if row is None:
            return None
        return _load_state(str(row["payload_json"]))

    def _sqlite_list_for_story(self, story_id: str) -> list[AgentHealthState]:
        with _sqlite_connect(self._store_dir) as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM worker_health_states
                WHERE story_id = ?
                ORDER BY updated_at DESC, worker_id ASC
                """,
                (story_id,),
            ).fetchall()
        return [_load_state(str(row["payload_json"])) for row in rows]

    def _pg_save(self, state: AgentHealthState) -> None:
        with _postgres_connect() as conn:
            conn.execute(
                """
                INSERT INTO worker_health_states
                    (story_id, worker_id, project_key, run_id, payload_json, updated_at)
                VALUES
                    (%(story_id)s, %(worker_id)s, %(project_key)s, %(run_id)s,
                     %(payload_json)s, %(updated_at)s)
                ON CONFLICT (story_id, worker_id) DO UPDATE SET
                    project_key = EXCLUDED.project_key,
                    run_id = EXCLUDED.run_id,
                    payload_json = EXCLUDED.payload_json,
                    updated_at = EXCLUDED.updated_at
                """,
                {
                    "story_id": state.story_id,
                    "worker_id": state.worker_id,
                    "project_key": state.project_key,
                    "run_id": state.run_id,
                    "payload_json": json.loads(_dump_state(state)),
                    "updated_at": state.last_updated,
                },
            )

    def _pg_load(
        self,
        *,
        story_id: str,
        worker_id: str,
    ) -> AgentHealthState | None:
        with _postgres_connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM worker_health_states
                WHERE story_id = %s AND worker_id = %s
                """,
                (story_id, worker_id),
            ).fetchone()
        if row is None:
            return None
        payload = row["payload_json"]
        return AgentHealthState.model_validate(payload)

    def _pg_list_for_story(self, story_id: str) -> list[AgentHealthState]:
        with _postgres_connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM worker_health_states
                WHERE story_id = %s
                ORDER BY updated_at DESC, worker_id ASC
                """,
                (story_id,),
            ).fetchall()
        return [AgentHealthState.model_validate(row["payload_json"]) for row in rows]


__all__ = [
    "StateBackendWorkerHealthRepository",
    "WorkerHealthStateRepository",
]
