"""GuardDecision persistence repository."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.backend.governance.guard_system.records import (
    GuardDecision,
    GuardDecisionOutcome,
)

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


def _postgres_database_url() -> str:
    url = os.environ.get("AGENTKIT_STATE_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "AGENTKIT_STATE_DATABASE_URL must be set when "
            "AGENTKIT_STATE_BACKEND=postgres"
        )
    return url


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row

    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        ensure_versioned_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class GuardDecisionRepository:
    """SQLite/Postgres-backed append-only GuardDecision repository."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def append(self, decision: GuardDecision) -> None:
        """Append one guard decision; duplicate identities fail closed."""
        if _is_postgres():
            with _postgres_connect() as conn:
                conn.execute(_PG_INSERT, _to_row(decision))
            return
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute(_SQLITE_INSERT, _to_row(decision))

    def list_for_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> tuple[GuardDecision, ...]:
        """Return decisions for a run ordered by decision time."""
        params = {
            "project_key": project_key,
            "story_id": story_id,
            "run_id": run_id,
        }
        if _is_postgres():
            with _postgres_connect() as conn:
                rows = conn.execute(_PG_SELECT, params).fetchall()
        else:
            with _sqlite_connect(self._store_dir) as conn:
                rows = conn.execute(_SQLITE_SELECT, params).fetchall()
        return tuple(_from_row(dict(row)) for row in rows)


_SQLITE_INSERT = """
    INSERT INTO guard_decisions (
        project_key, story_id, run_id, flow_id, guard_decision_id, guard_key,
        outcome, decided_at, node_id, reason, evidence_ref
    ) VALUES (
        :project_key, :story_id, :run_id, :flow_id, :guard_decision_id,
        :guard_key, :outcome, :decided_at, :node_id, :reason, :evidence_ref
    )
"""

_PG_INSERT = """
    INSERT INTO guard_decisions (
        project_key, story_id, run_id, flow_id, guard_decision_id, guard_key,
        outcome, decided_at, node_id, reason, evidence_ref
    ) VALUES (
        %(project_key)s, %(story_id)s, %(run_id)s, %(flow_id)s,
        %(guard_decision_id)s, %(guard_key)s, %(outcome)s, %(decided_at)s,
        %(node_id)s, %(reason)s, %(evidence_ref)s
    )
"""

_SQLITE_SELECT = """
    SELECT * FROM guard_decisions
    WHERE project_key=:project_key AND story_id=:story_id AND run_id=:run_id
    ORDER BY decided_at, guard_decision_id
"""

_PG_SELECT = """
    SELECT * FROM guard_decisions
    WHERE project_key=%(project_key)s AND story_id=%(story_id)s
      AND run_id=%(run_id)s
    ORDER BY decided_at, guard_decision_id
"""


def _to_row(decision: GuardDecision) -> dict[str, object]:
    return {
        "project_key": decision.project_key,
        "story_id": decision.story_id,
        "run_id": decision.run_id,
        "flow_id": decision.flow_id,
        "guard_decision_id": decision.guard_decision_id,
        "guard_key": decision.guard_key,
        "outcome": decision.outcome.value,
        "decided_at": decision.decided_at.isoformat(),
        "node_id": decision.node_id,
        "reason": decision.reason,
        "evidence_ref": decision.evidence_ref,
    }


def _from_row(row: dict[str, Any]) -> GuardDecision:
    return GuardDecision(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        flow_id=str(row["flow_id"]),
        guard_decision_id=str(row["guard_decision_id"]),
        guard_key=str(row["guard_key"]),
        outcome=GuardDecisionOutcome(str(row["outcome"])),
        decided_at=datetime.fromisoformat(str(row["decided_at"])),
        node_id=_optional_str(row.get("node_id")),
        reason=_optional_str(row.get("reason")),
        evidence_ref=_optional_str(row.get("evidence_ref")),
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = ["GuardDecisionRepository"]
