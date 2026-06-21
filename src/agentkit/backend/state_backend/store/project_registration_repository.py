"""StateBackendProjectRegistrationRepository — project_registry persistence.

Productive SQLite/Postgres implementation of the
``ProjectRegistrationRepository`` Protocol (``agentkit.backend.installer.repository``),
backing Installer-Checkpoint 7 (FK-50 §50.3 CP 7).

Design (mirrors ``mode_lock_repository.py`` / ``skill_binding_repository.py``):

- Postgres is the canonical truth (DK-05 §5); SQLite is the test-only parallel
  path (``AGENTKIT_ALLOW_SQLITE=1``). No co-equal dual-backend operation.
- The ``project_registry`` DDL is SINGLE SOURCE OF TRUTH in
  ``postgres_schema.sql`` (Postgres) / ``sqlite_store._ensure_schema`` (SQLite).
  This adapter carries no second DDL truth; it bootstraps the canonical schema
  and only reads/writes.
- ``save`` is a plain INSERT (initial registration). The idempotency/upgrade
  decision (same digest -> SKIPPED, divergent digest -> ``update_upgraded``)
  lives in the installer CP 7 wiring, not here — the repository stays a thin,
  honest persistence port.
- Fail-closed: corrupt rows propagate the mapper exception (NO ERROR BYPASSING).

Architecture Conformance:
    The installer BC (BC 12) knows only the ``ProjectRegistrationRepository``
    Protocol; this adapter is wired in the composition root.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.backend.installer.registration import ProjectRegistration, RuntimeProfile

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Backend detection (same pattern as skill_binding_repository.py)
# ---------------------------------------------------------------------------


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

    from agentkit.backend.state_backend import postgres_store
    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

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


# ---------------------------------------------------------------------------
# Mapping (local, like mode_lock_repository — no shared mapper truth)
# ---------------------------------------------------------------------------


def _require_one_row(rowcount: int, project_key: str, operation: str) -> None:
    """FAIL-CLOSED guard: a lifecycle mutation must have touched an existing row.

    A 0-row ``UPDATE`` means the targeted ``project_key`` is not registered. The
    mutation contract (``update_verified``/``update_upgraded``) is "for an existing
    registration"; silently treating a no-op as success would let a missing or
    mistyped key pass unnoticed (story W6, FAIL-CLOSED / NO ERROR BYPASSING).

    Args:
        rowcount: Rows affected by the UPDATE.
        project_key: The targeted project key (for the error message).
        operation: The mutation name (for the error message).

    Raises:
        LookupError: when ``rowcount`` is not exactly 1.
    """
    if rowcount != 1:
        raise LookupError(
            f"{operation}: no project_registry row for project_key={project_key!r} "
            f"(affected rows={rowcount}); a lifecycle mutation requires an existing "
            "registration.",
        )


def _ts(value: datetime | None, *, is_postgres: bool) -> Any:
    """Bind a timestamp for the target backend.

    Postgres ``registered_at``/``last_*_at`` are ``TIMESTAMPTZ`` (story §2.1.1):
    pass the native ``datetime`` so psycopg adapts it directly and the read path
    returns a tz-aware ``datetime`` (no string round-trip). SQLite stores ISO-8601
    TEXT (no native timestamptz affinity), so it gets the ``isoformat()`` string.
    """
    if value is None:
        return None
    return value if is_postgres else value.isoformat()


def _registration_to_row(
    registration: ProjectRegistration, *, is_postgres: bool
) -> dict[str, Any]:
    """Project a :class:`ProjectRegistration` into a ``project_registry`` row."""

    return {
        "project_key": registration.project_key,
        "project_root": str(registration.project_root),
        "github_owner": registration.github_owner,
        "github_repo": registration.github_repo,
        "runtime_profile": registration.runtime_profile.value,
        "config_version": registration.config_version,
        "config_digest": registration.config_digest,
        "registered_at": _ts(registration.registered_at, is_postgres=is_postgres),
        "last_verified_at": _ts(registration.last_verified_at, is_postgres=is_postgres),
        "last_upgraded_at": _ts(registration.last_upgraded_at, is_postgres=is_postgres),
    }


def _row_to_registration(row: dict[str, Any]) -> ProjectRegistration:
    """Reconstruct a :class:`ProjectRegistration` from a ``project_registry`` row."""

    def _dt(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    registered_at = _dt(row["registered_at"])
    if registered_at is None:  # pragma: no cover - NOT NULL column, defensive
        raise ValueError("project_registry.registered_at must not be NULL")
    return ProjectRegistration(
        project_key=str(row["project_key"]),
        project_root=Path(str(row["project_root"])),
        github_owner=str(row["github_owner"]),
        github_repo=str(row["github_repo"]),
        runtime_profile=RuntimeProfile(str(row["runtime_profile"])),
        config_version=str(row["config_version"]),
        config_digest=str(row["config_digest"]),
        registered_at=registered_at,
        last_verified_at=_dt(row.get("last_verified_at")),
        last_upgraded_at=_dt(row.get("last_upgraded_at")),
    )


_INSERT_COLUMNS = (
    "project_key, project_root, github_owner, github_repo, runtime_profile, "
    "config_version, config_digest, registered_at, last_verified_at, "
    "last_upgraded_at"
)
_SQLITE_INSERT = f"""
    INSERT INTO project_registry ({_INSERT_COLUMNS}) VALUES (
        :project_key, :project_root, :github_owner, :github_repo,
        :runtime_profile, :config_version, :config_digest, :registered_at,
        :last_verified_at, :last_upgraded_at
    )
"""
_PG_INSERT = f"""
    INSERT INTO project_registry ({_INSERT_COLUMNS}) VALUES (
        %(project_key)s, %(project_root)s, %(github_owner)s, %(github_repo)s,
        %(runtime_profile)s, %(config_version)s, %(config_digest)s,
        %(registered_at)s, %(last_verified_at)s, %(last_upgraded_at)s
    )
"""


class StateBackendProjectRegistrationRepository:
    """SQLite/Postgres implementation of ``ProjectRegistrationRepository``.

    Backend selected via ``AGENTKIT_STATE_BACKEND`` (``sqlite``/``postgres``);
    Postgres is canonical, SQLite is the test-parallel path
    (``AGENTKIT_ALLOW_SQLITE=1``).

    Args:
        store_dir: Base directory for the SQLite store (Postgres ignores it).
            Default: ``Path.cwd()``.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    # ------------------------------------------------------------------
    # get
    # ------------------------------------------------------------------

    def get(self, project_key: str) -> ProjectRegistration | None:
        """Return the registration for ``project_key``, or ``None`` if absent."""
        if _is_postgres():
            row = self._pg_one(
                "SELECT * FROM project_registry WHERE project_key = %s",
                (project_key,),
            )
        else:
            row = self._sqlite_one(
                "SELECT * FROM project_registry WHERE project_key = ?",
                (project_key,),
            )
        return _row_to_registration(row) if row is not None else None

    # ------------------------------------------------------------------
    # save (initial registration)
    # ------------------------------------------------------------------

    def save(self, registration: ProjectRegistration) -> None:
        """Insert a new registration (FAIL-CLOSED on PK/UNIQUE collision)."""
        if _is_postgres():
            with _postgres_connect() as conn:
                conn.execute(_PG_INSERT, _registration_to_row(registration, is_postgres=True))
        else:
            with _sqlite_connect(self._store_dir) as conn:
                conn.execute(
                    _SQLITE_INSERT, _registration_to_row(registration, is_postgres=False)
                )

    # ------------------------------------------------------------------
    # update_verified
    # ------------------------------------------------------------------

    def update_verified(self, project_key: str, verified_at: datetime) -> None:
        """Set ``last_verified_at`` for an existing registration (FAIL-CLOSED).

        Raises:
            LookupError: when no ``project_registry`` row matches ``project_key``.
                A lifecycle mutation only applies to an EXISTING registration; a
                0-row update is a silent no-op and must fail closed (story W6 /
                FAIL-CLOSED), not be reported as success.
        """
        if _is_postgres():
            with _postgres_connect() as conn:
                cursor = conn.execute(
                    "UPDATE project_registry SET last_verified_at = %s "
                    "WHERE project_key = %s",
                    (verified_at, project_key),
                )
                _require_one_row(cursor.rowcount, project_key, "update_verified")
        else:
            with _sqlite_connect(self._store_dir) as conn:
                cursor = conn.execute(
                    "UPDATE project_registry SET last_verified_at = ? "
                    "WHERE project_key = ?",
                    (verified_at.isoformat(), project_key),
                )
                _require_one_row(cursor.rowcount, project_key, "update_verified")

    # ------------------------------------------------------------------
    # update_upgraded
    # ------------------------------------------------------------------

    def update_upgraded(
        self, project_key: str, upgraded_at: datetime, new_digest: str
    ) -> None:
        """Set ``last_upgraded_at`` and the new ``config_digest`` (upgrade path).

        Raises:
            LookupError: when no ``project_registry`` row matches ``project_key``
                (FAIL-CLOSED — an upgrade targets an existing registration; a
                0-row update must not be silently treated as success, story W6).
        """
        if _is_postgres():
            with _postgres_connect() as conn:
                cursor = conn.execute(
                    "UPDATE project_registry SET last_upgraded_at = %s, "
                    "config_digest = %s WHERE project_key = %s",
                    (upgraded_at, new_digest, project_key),
                )
                _require_one_row(cursor.rowcount, project_key, "update_upgraded")
        else:
            with _sqlite_connect(self._store_dir) as conn:
                cursor = conn.execute(
                    "UPDATE project_registry SET last_upgraded_at = ?, "
                    "config_digest = ? WHERE project_key = ?",
                    (upgraded_at.isoformat(), new_digest, project_key),
                )
                _require_one_row(cursor.rowcount, project_key, "update_upgraded")

    # ------------------------------------------------------------------
    # list_all
    # ------------------------------------------------------------------

    def list_all(self) -> list[ProjectRegistration]:
        """Return all registrations, ordered by ``project_key``."""
        query = "SELECT * FROM project_registry ORDER BY project_key"
        if _is_postgres():
            with _postgres_connect() as conn:
                rows = conn.execute(query).fetchall()
        else:
            with _sqlite_connect(self._store_dir) as conn:
                rows = conn.execute(query).fetchall()
        return [_row_to_registration(dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # internal single-row helpers
    # ------------------------------------------------------------------

    def _sqlite_one(
        self, query: str, params: tuple[Any, ...]
    ) -> dict[str, Any] | None:
        with _sqlite_connect(self._store_dir) as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row is not None else None

    def _pg_one(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with _postgres_connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row is not None else None


__all__ = ["StateBackendProjectRegistrationRepository"]
