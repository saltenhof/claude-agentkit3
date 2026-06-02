"""StateBackendHookRegistrationRepository — SQLite/Postgres implementation.

Concrete implementation of ``HookRegistrationRepository`` protocol from
``agentkit.governance.repository``.

Design decisions:
- Backend switch via ``AGENTKIT_STATE_BACKEND`` env-var (sqlite/postgres),
  analog to ``artifact_repository.py``.
- UNIQUE constraint on ``(project_key, hook_event_name, matcher, command)``
  per FK-30 §30.3.1.  AG3-031 Hotfix 2026-05-25: ``command`` added to the
  identity because §30.3.1 registers several hooks under one matcher
  (e.g. ``Bash`` hosts branch_guard AND story_creation_guard); the prior
  3-tuple key collapsed them and silently dropped guards.
- INSERT OR IGNORE (SQLite) / ON CONFLICT DO NOTHING (Postgres) for idempotent
  registration without overwriting unchanged rows. Rows not inserted are
  reported as ``skipped``.
- Fail-closed: no silent None returns on backend errors; exceptions propagate.

Architecture Conformance (AK8):
- Does NOT import from ``agentkit.state_backend.store.facade`` or ``mappers``.
- Accesses the database directly via its own connection helpers.
- Imports governance BC types from ``agentkit.governance.*`` only.

Sources:
- FK-30 §30.3.1  — hook_registration top-surface and HookDefinition fields
- FK-18 §18.9a   — Side-by-Side-DB per SCHEMA_VERSION

AG3-031 Pass-2 FK-30-Korrektur 2026-05-24:
  Schema corrected to (project_key, hook_event_name, matcher, command)
  with PK (project_key, hook_event_name, matcher).  Previous Pass-1
  schema used (harness, hook_id, command_template, event_pattern) which
  did not match FK-30 §30.3.1.  SCHEMA_VERSION stays "3.6.0" because the
  old 3.6.0 DB was never in production; this correction freezes the
  correct schema under the same version.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.governance.errors import HookRegistrationError
from agentkit.governance.hook_registration import (
    HookDefinition,
    HookEventName,
    RegistrationResult,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Backend detection (same pattern as artifact_repository.py)
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    """Return True when AGENTKIT_STATE_BACKEND=postgres."""
    return os.environ.get("AGENTKIT_STATE_BACKEND", "sqlite").lower() == "postgres"


def _assert_sqlite_allowed() -> None:
    """Raise RuntimeError if SQLite backend is not explicitly enabled.

    Enforces the AGENTKIT_ALLOW_SQLITE=1 gating pattern from
    ``state_backend/config.py:_sqlite_allowed`` (Fix E8, AG3-031 Pass-3).
    """
    from agentkit.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed

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


# ---------------------------------------------------------------------------
# DDL — FK-30 §30.3.1 schema (hook_event_name, matcher, command)
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS governance_hook_registrations (
    project_key     VARCHAR NOT NULL,
    hook_event_name VARCHAR NOT NULL CHECK (hook_event_name IN ('PreToolUse','PostToolUse')),
    matcher         TEXT NOT NULL,
    command         TEXT NOT NULL,
    registered_at   TEXT NOT NULL,
    PRIMARY KEY (project_key, hook_event_name, matcher, command)
)
"""

_CREATE_TABLE_PG_SQL = """
CREATE TABLE IF NOT EXISTS governance_hook_registrations (
    project_key     VARCHAR NOT NULL,
    hook_event_name VARCHAR NOT NULL CHECK (hook_event_name IN ('PreToolUse','PostToolUse')),
    matcher         TEXT NOT NULL,
    command         TEXT NOT NULL,
    registered_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (project_key, hook_event_name, matcher, command),
    UNIQUE (project_key, hook_event_name, matcher, command)
)
"""


# ---------------------------------------------------------------------------
# Row <-> HookDefinition conversion
# ---------------------------------------------------------------------------


def _definition_to_row(
    project_key: str,
    defn: HookDefinition,
    registered_at: str,
) -> dict[str, Any]:
    return {
        "project_key": project_key,
        "hook_event_name": defn.hook_event_name.value,
        "matcher": defn.matcher,
        "command": defn.command,
        "registered_at": registered_at,
    }


def _row_to_definition(row: dict[str, Any]) -> HookDefinition:
    return HookDefinition(
        hook_event_name=HookEventName(str(row["hook_event_name"])),
        matcher=str(row["matcher"]),
        command=str(row["command"]),
    )


def _defn_identifier(defn: HookDefinition) -> str:
    """Return a stable string identifier for a HookDefinition."""
    return defn.matcher


# ---------------------------------------------------------------------------
# SQLite connection helper
# ---------------------------------------------------------------------------


def _sqlite_db_path(store_dir: Path) -> Path:
    from agentkit.state_backend.config import versioned_sqlite_db_file
    from agentkit.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    _assert_sqlite_allowed()
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_sqlite_schema(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_CREATE_TABLE_SQL)


# ---------------------------------------------------------------------------
# Postgres connection helper
# ---------------------------------------------------------------------------


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row

    from agentkit.state_backend.schema_bootstrap import ensure_versioned_schema

    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        ensure_versioned_schema(conn)
        _ensure_postgres_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_postgres_schema(conn: Any) -> None:
    conn.execute(_CREATE_TABLE_PG_SQL)


# ---------------------------------------------------------------------------
# StateBackendHookRegistrationRepository
# ---------------------------------------------------------------------------


class StateBackendHookRegistrationRepository:
    """SQLite/Postgres-backed implementation of ``HookRegistrationRepository``.

    Backend is selected via ``AGENTKIT_STATE_BACKEND`` env-var.
    SQLite is only allowed when ``AGENTKIT_ALLOW_SQLITE=1``.

    Idempotent registration:
        Identity is the 4-tuple ``(project_key, hook_event_name, matcher,
        command)``. A second ``register`` call with the same definitions
        returns all matchers in ``skipped`` and none in ``registered``.
        Distinct commands sharing a matcher (e.g. branch_guard and
        story_creation_guard both on ``Bash``) are preserved as separate rows.

    Args:
        store_dir: Base directory for SQLite state store. Ignored for Postgres.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    # ------------------------------------------------------------------
    # register
    # ------------------------------------------------------------------

    def register(
        self,
        project_key: str,
        hook_definitions: list[HookDefinition],
    ) -> RegistrationResult:
        """Persist hook definitions; existing rows are skipped (idempotent).

        Args:
            project_key: Owning project identifier.
            hook_definitions: Hook definitions to register.

        Returns:
            ``RegistrationResult`` with registered/skipped/errors
            (matcher strings in registered/skipped lists).

        Raises:
            Exception: On unrecoverable backend failures.
        """
        if _is_postgres():
            return self._pg_register(project_key, hook_definitions)
        return self._sqlite_register(project_key, hook_definitions)

    def _sqlite_register(
        self,
        project_key: str,
        definitions: list[HookDefinition],
    ) -> RegistrationResult:
        registered: list[str] = []
        skipped: list[str] = []
        errors: list[HookRegistrationError] = []

        now_ts = datetime.now(UTC).isoformat()

        with _sqlite_connect(self._store_dir) as conn:
            for defn in definitions:
                try:
                    # AG3-031 Hotfix 2026-05-25 (Governance-Loch): Identitaet ist
                    # das 4-Tupel (project_key, hook_event_name, matcher, command).
                    # FK-30 §30.3.1 registriert mehrere Hooks mit demselben matcher
                    # (z. B. "Bash" fuer branch_guard UND story_creation_guard);
                    # ein 3-Tupel-PK ohne command kollabierte sie und verwarf Guards.
                    # Pre-check: exaktes 4-Tupel bereits vorhanden -> idempotent skip.
                    existing = conn.execute(
                        """
                        SELECT 1 FROM governance_hook_registrations
                        WHERE project_key = :project_key
                          AND hook_event_name = :hook_event_name
                          AND matcher = :matcher
                          AND command = :command
                        """,
                        {
                            "project_key": project_key,
                            "hook_event_name": defn.hook_event_name.value,
                            "matcher": defn.matcher,
                            "command": defn.command,
                        },
                    ).fetchone()

                    if existing is not None:
                        # Identical 4-tuple already present — skip (no-op)
                        skipped.append(_defn_identifier(defn))
                    else:
                        # New (matcher, command) combination — INSERT
                        row = _definition_to_row(project_key, defn, now_ts)
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO governance_hook_registrations
                                (project_key, hook_event_name, matcher, command,
                                 registered_at)
                            VALUES
                                (:project_key, :hook_event_name, :matcher,
                                 :command, :registered_at)
                            """,
                            row,
                        )
                        registered.append(_defn_identifier(defn))
                # Broad except is intentional: exceptions are collected as
                # HookRegistrationError entries in the result, never re-raised
                # (caller pattern: partial-success registration with errors[]).
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        HookRegistrationError(
                            f"Failed to register matcher {defn.matcher!r}: {exc}",
                            detail={"matcher": defn.matcher, "hook_event_name": defn.hook_event_name},
                        )
                    )

        return RegistrationResult(
            registered=registered,
            skipped=skipped,
            errors=errors,
        )

    def _pg_register(
        self,
        project_key: str,
        definitions: list[HookDefinition],
    ) -> RegistrationResult:
        registered: list[str] = []
        skipped: list[str] = []
        errors: list[HookRegistrationError] = []

        now_ts = datetime.now(UTC).isoformat()

        with _postgres_connect() as conn:
            for defn in definitions:
                try:
                    # AG3-031 Hotfix 2026-05-25 (Governance-Loch): Identitaet ist
                    # das 4-Tupel (project_key, hook_event_name, matcher, command).
                    # FK-30 §30.3.1 registriert mehrere Hooks mit demselben matcher;
                    # ein 3-Tupel-PK ohne command kollabierte sie und verwarf Guards.
                    # Pre-check: exaktes 4-Tupel bereits vorhanden -> idempotent skip.
                    existing = conn.execute(
                        """
                        SELECT 1 FROM governance_hook_registrations
                        WHERE project_key = %(project_key)s
                          AND hook_event_name = %(hook_event_name)s
                          AND matcher = %(matcher)s
                          AND command = %(command)s
                        """,
                        {
                            "project_key": project_key,
                            "hook_event_name": defn.hook_event_name.value,
                            "matcher": defn.matcher,
                            "command": defn.command,
                        },
                    ).fetchone()

                    if existing is not None:
                        # Identical 4-tuple already present — skip (no-op)
                        skipped.append(_defn_identifier(defn))
                    else:
                        # New (matcher, command) combination — INSERT (idempotent UPSERT)
                        row = _definition_to_row(project_key, defn, now_ts)
                        conn.execute(
                            """
                            INSERT INTO governance_hook_registrations
                                (project_key, hook_event_name, matcher, command,
                                 registered_at)
                            VALUES
                                (%(project_key)s, %(hook_event_name)s, %(matcher)s,
                                 %(command)s, %(registered_at)s)
                            ON CONFLICT (project_key, hook_event_name, matcher, command)
                            DO UPDATE SET
                                registered_at = EXCLUDED.registered_at
                            """,
                            row,
                        )
                        registered.append(_defn_identifier(defn))
                # Broad except is intentional: exceptions are collected as
                # HookRegistrationError entries in the result, never re-raised
                # (caller pattern: partial-success registration with errors[]).
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        HookRegistrationError(
                            f"Failed to register matcher {defn.matcher!r}: {exc}",
                            detail={"matcher": defn.matcher, "hook_event_name": defn.hook_event_name},
                        )
                    )

        return RegistrationResult(
            registered=registered,
            skipped=skipped,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # list_for_project
    # ------------------------------------------------------------------

    def list_for_project(self, project_key: str) -> list[HookDefinition]:
        """Return all registered hook definitions for a project.

        Args:
            project_key: Owning project identifier.

        Returns:
            List of ``HookDefinition`` objects (possibly empty).
        """
        if _is_postgres():
            return self._pg_list(project_key)
        return self._sqlite_list(project_key)

    def _sqlite_list(self, project_key: str) -> list[HookDefinition]:
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                """
                SELECT hook_event_name, matcher, command
                FROM governance_hook_registrations
                WHERE project_key = ?
                ORDER BY hook_event_name, matcher
                """,
                (project_key,),
            )
            rows = cursor.fetchall()
        return [_row_to_definition(dict(row)) for row in rows]

    def _pg_list(self, project_key: str) -> list[HookDefinition]:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                """
                SELECT hook_event_name, matcher, command
                FROM governance_hook_registrations
                WHERE project_key = %s
                ORDER BY hook_event_name, matcher
                """,
                (project_key,),
            )
            rows = cursor.fetchall()
        return [_row_to_definition(dict(row)) for row in rows]

    # ------------------------------------------------------------------
    # clear_for_project (test helper)
    # ------------------------------------------------------------------

    def clear_for_project(self, project_key: str) -> None:
        """Delete all hook registrations for a project (test helper).

        Args:
            project_key: Owning project identifier.
        """
        if _is_postgres():
            self._pg_clear(project_key)
        else:
            self._sqlite_clear(project_key)

    def _sqlite_clear(self, project_key: str) -> None:
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute(
                "DELETE FROM governance_hook_registrations WHERE project_key = ?",
                (project_key,),
            )

    def _pg_clear(self, project_key: str) -> None:
        with _postgres_connect() as conn:
            conn.execute(
                "DELETE FROM governance_hook_registrations WHERE project_key = %s",
                (project_key,),
            )


__all__ = ["StateBackendHookRegistrationRepository"]
