"""StateBackendSkillBindingRepository — SQLite/Postgres impl of SkillBindingRepository.

Productive persistence for the agent-skills BC ``SkillBinding`` records
(AG3-048, FK-43 §43.4.1, bc-cut-decisions.md §BC 11). Implements the
``SkillBindingRepository`` Protocol defined in AG3-027
(``agentkit.backend.skills.repository``).

Design (mirrors ``fc_incident_repository.py`` / ``artifact_repository.py``):

- Postgres is the canonical truth (concept/domain-design
  /05-telemetrie-und-metriken.md §5); SQLite carries the IDENTICAL schema as a
  test-parallel path (only under ``AGENTKIT_ALLOW_SQLITE=1``). No
  co-equal dual-backend operation.
- The ``skill_bindings`` DDL is SINGLE SOURCE OF TRUTH in
  ``postgres_schema.sql`` (Postgres) resp. ``sqlite_store._ensure_schema``
  (SQLite). This adapter keeps NO second DDL truth; it bootstraps the
  canonical schema and only writes/reads.
- ``save`` is an UPSERT on the natural key column
  ``(project_key, skill_name)`` (FK-43: exactly one binding per project+skill).
- Fail-closed: on corrupt rows the mapper exception propagates
  (NO ERROR BYPASSING); no silent ``None`` returns on backend errors.

Architecture Conformance:
    The ``agent-skills`` BC does NOT know this adapter (it only imports the
    ``SkillBindingRepository`` protocol). The wiring happens in the
    composition root (``build_skills``).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.backend.state_backend.store.mappers import (
    skill_binding_row_to_record,
    skill_binding_to_row,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentkit.backend.skills.binding import SkillBinding


# ---------------------------------------------------------------------------
# Backend detection (same pattern as fc_incident_repository.py)
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    """Return True when the canonical backend is Postgres (load_state_backend_config)."""
    from agentkit.backend.state_backend.config import (
        StateBackendKind,
        load_state_backend_config,
    )

    return load_state_backend_config().backend is StateBackendKind.POSTGRES


def _assert_sqlite_allowed() -> None:
    """Raise RuntimeError if the SQLite test-parallel path is not enabled."""
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
    """Open a SQLite connection and bootstrap the canonical schema.

    DDL ownership lives in ``sqlite_store._ensure_schema`` (SINGLE SOURCE OF
    TRUTH); this function only guarantees that ``skill_bindings`` exists.
    """
    from agentkit.backend.state_backend import sqlite_store

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
    """Open a psycopg connection with the canonical versioned schema bootstrapped."""
    import psycopg
    from psycopg.rows import dict_row

    from agentkit.backend.state_backend import postgres_store
    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        ensure_versioned_schema(conn)
        # Bootstrap via the canonical Postgres schema owner (SINGLE SOURCE OF
        # TRUTH, symmetric to _sqlite_connect): guarantees skill_bindings exists
        # before the adapter writes/reads. Idempotent (CREATE IF NOT EXISTS).
        postgres_store._ensure_schema_once(postgres_store._CompatConnection(conn))
        conn.commit()
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# StateBackendSkillBindingRepository
# ---------------------------------------------------------------------------


class StateBackendSkillBindingRepository:
    """SQLite/Postgres implementation of the ``SkillBindingRepository`` Protocol.

    Backend is selected via ``AGENTKIT_STATE_BACKEND`` (``sqlite``/``postgres``);
    Postgres is canonical, SQLite is the test-parallel path
    (``AGENTKIT_ALLOW_SQLITE=1``).

    ``save`` upserts on the natural key ``(project_key, skill_name)``: a binding
    re-saved (e.g. the BOUND->VERIFIED lifecycle transition in
    ``Skills.bind_skill``) updates the existing row in place.

    Args:
        store_dir: Base directory for the SQLite store (Postgres ignores it).
            Default: ``Path.cwd()``.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    # ------------------------------------------------------------------
    # save (upsert)
    # ------------------------------------------------------------------

    def save(self, binding: SkillBinding) -> None:
        """Persist or replace a ``SkillBinding`` (upsert on project_key+skill_name).

        Args:
            binding: The binding to save.
        """
        row = skill_binding_to_row(binding)
        if _is_postgres():
            self._pg_save(row)
        else:
            self._sqlite_save(row)

    def _sqlite_save(self, row: dict[str, Any]) -> None:
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute(
                """
                INSERT INTO skill_bindings (
                    binding_id, project_key, skill_name, bundle_id,
                    bundle_version, target_path, binding_mode, status, pinned_at
                ) VALUES (
                    :binding_id, :project_key, :skill_name, :bundle_id,
                    :bundle_version, :target_path, :binding_mode, :status,
                    :pinned_at
                )
                ON CONFLICT (project_key, skill_name) DO UPDATE SET
                    binding_id=excluded.binding_id,
                    bundle_id=excluded.bundle_id,
                    bundle_version=excluded.bundle_version,
                    target_path=excluded.target_path,
                    binding_mode=excluded.binding_mode,
                    status=excluded.status,
                    pinned_at=excluded.pinned_at
                """,
                row,
            )

    def _pg_save(self, row: dict[str, Any]) -> None:
        with _postgres_connect() as conn:
            conn.execute(
                """
                INSERT INTO skill_bindings (
                    binding_id, project_key, skill_name, bundle_id,
                    bundle_version, target_path, binding_mode, status, pinned_at
                ) VALUES (
                    %(binding_id)s, %(project_key)s, %(skill_name)s,
                    %(bundle_id)s, %(bundle_version)s, %(target_path)s,
                    %(binding_mode)s, %(status)s, %(pinned_at)s
                )
                ON CONFLICT (project_key, skill_name) DO UPDATE SET
                    binding_id=excluded.binding_id,
                    bundle_id=excluded.bundle_id,
                    bundle_version=excluded.bundle_version,
                    target_path=excluded.target_path,
                    binding_mode=excluded.binding_mode,
                    status=excluded.status,
                    pinned_at=excluded.pinned_at
                """,
                row,
            )

    # ------------------------------------------------------------------
    # load
    # ------------------------------------------------------------------

    def load(self, project_key: str, skill_name: str) -> SkillBinding | None:
        """Load a single binding by its natural key, or ``None`` if absent.

        Args:
            project_key: Target project key.
            skill_name: Logical skill name.

        Returns:
            The matching ``SkillBinding`` or ``None``.
        """
        if _is_postgres():
            return self._pg_load(project_key, skill_name)
        return self._sqlite_load(project_key, skill_name)

    def _sqlite_load(self, project_key: str, skill_name: str) -> SkillBinding | None:
        with _sqlite_connect(self._store_dir) as conn:
            row = conn.execute(
                "SELECT * FROM skill_bindings "
                "WHERE project_key = ? AND skill_name = ?",
                (project_key, skill_name),
            ).fetchone()
        if row is None:
            return None
        return skill_binding_row_to_record(dict(row))

    def _pg_load(self, project_key: str, skill_name: str) -> SkillBinding | None:
        with _postgres_connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_bindings "
                "WHERE project_key = %s AND skill_name = %s",
                (project_key, skill_name),
            ).fetchone()
        if row is None:
            return None
        return skill_binding_row_to_record(dict(row))

    # ------------------------------------------------------------------
    # list_for_project
    # ------------------------------------------------------------------

    def list_for_project(self, project_key: str) -> list[SkillBinding]:
        """Return all bindings for a project, sorted by ``skill_name``.

        Args:
            project_key: Target project key.

        Returns:
            Deterministically sorted list of ``SkillBinding`` objects.
        """
        rows = (
            self._pg_list(project_key)
            if _is_postgres()
            else self._sqlite_list(project_key)
        )
        return [skill_binding_row_to_record(r) for r in rows]

    def _sqlite_list(self, project_key: str) -> list[dict[str, Any]]:
        with _sqlite_connect(self._store_dir) as conn:
            rows = conn.execute(
                "SELECT * FROM skill_bindings WHERE project_key = ? "
                "ORDER BY skill_name",
                (project_key,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _pg_list(self, project_key: str) -> list[dict[str, Any]]:
        with _postgres_connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_bindings WHERE project_key = %s "
                "ORDER BY skill_name",
                (project_key,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # delete (transactional rollback primitive)
    # ------------------------------------------------------------------

    def delete(self, project_key: str, skill_name: str) -> None:
        """Remove a binding by its natural key (no-op if absent).

        Used by the installer to undo persisted bindings when binding the
        mandatory-skill set fails part-way (FAIL-CLOSED, no partial install).

        Args:
            project_key: Target project key.
            skill_name: Logical skill name.
        """
        if _is_postgres():
            self._pg_delete(project_key, skill_name)
        else:
            self._sqlite_delete(project_key, skill_name)

    def _sqlite_delete(self, project_key: str, skill_name: str) -> None:
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute(
                "DELETE FROM skill_bindings "
                "WHERE project_key = ? AND skill_name = ?",
                (project_key, skill_name),
            )

    def _pg_delete(self, project_key: str, skill_name: str) -> None:
        with _postgres_connect() as conn:
            conn.execute(
                "DELETE FROM skill_bindings "
                "WHERE project_key = %s AND skill_name = %s",
                (project_key, skill_name),
            )


__all__ = ["StateBackendSkillBindingRepository"]
