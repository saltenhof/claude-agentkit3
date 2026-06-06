"""Idempotent schema-migration runner (FK-62 §62.4, FK-18 §18.9a).

The ``MigrationRunner`` applies versioned DDL migrations exactly once per schema
version and records each applied version in a ``schema_versions`` cursor table
(``PRIMARY KEY (version)``, ``applied_at``). It is the AG3-038 realisation of
FK-62 §62.4's ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` /
``CREATE TABLE IF NOT EXISTS`` strategy with the FK-62 §62.4.3 version cursor.

Idempotency contract (story AC5):

- Every migration statement is itself idempotent (``CREATE ... IF NOT EXISTS``)
  — no ``DROP``/``RECREATE``.
- A version already present in ``schema_versions`` is skipped, so a double run
  produces no error, no duplicate cursor row, and no schema churn.
- The cursor insert uses ``INSERT ... ON CONFLICT (version) DO NOTHING`` so even
  a forced re-apply cannot create a duplicate cursor row.

Backend-agnostic: the runner talks to any connection exposing
``execute(sql, params=())`` with ``?`` placeholders. Both ``sqlite3.Connection``
and the Postgres ``_CompatConnection`` (which rewrites ``?`` to ``%s``) satisfy
this, so the SAME runner drives both backends (story AC5 "idempotent on both
backends").
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from agentkit.boundary.shared.time import now_iso
from agentkit.state_backend.postgres_store import iter_sql_statements

if TYPE_CHECKING:
    from collections.abc import Sequence

_VERSIONS_DIR = Path(__file__).with_name("versions")

# Ordered registry of (schema_version, ddl_file). New migrations append here.
_MIGRATIONS: tuple[tuple[str, str], ...] = (("3.4", "v_3_4_analytics.sql"),)


class _MigrationCursor(Protocol):
    """The fetch surface the runner needs from an ``execute`` result.

    Both sqlite3 cursors (tuple/``Row`` rows) and the psycopg ``dict_row``
    cursor (mapping rows) satisfy this; ``_version_of`` reads either shape.
    """

    def fetchall(self) -> Sequence[Any]:
        """Return all result rows."""
        ...


class _MigrationConnection(Protocol):
    """Minimal connection surface the runner needs (sqlite3 / _CompatConnection)."""

    def execute(
        self, query: str, params: Sequence[object] = ...
    ) -> _MigrationCursor:
        """Execute a single statement with ``?`` placeholders, return a cursor."""
        ...


def _version_of(row: Any) -> str:
    """Read the ``version`` value from a tuple/``Row`` or a ``dict_row`` mapping.

    The runner drives both sqlite3 (positional rows) and the psycopg
    ``dict_row`` cursor (mapping rows), so the ``version`` column is read by key
    when the row is a mapping and positionally otherwise.
    """
    if isinstance(row, Mapping):
        return str(row["version"])
    return str(row[0])


class MigrationRunner:
    """Apply versioned analytics migrations idempotently with a version cursor."""

    def __init__(self, versions_dir: Path | None = None) -> None:
        """Initialise the runner.

        Args:
            versions_dir: Directory holding the ``v_*.sql`` migration files.
                Defaults to the package ``versions/`` directory.
        """
        self._versions_dir = versions_dir or _VERSIONS_DIR

    def ensure_cursor_table(self, conn: _MigrationConnection) -> None:
        """Create the ``schema_versions`` cursor table if it does not exist.

        FK-62 §62.4.3: ``PRIMARY KEY (version)`` so each version is recorded at
        most once; ``applied_at`` is an ISO-8601 instant. Portable DDL valid on
        both SQLite and Postgres.
        """
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_versions ("
            "version TEXT NOT NULL, "
            "applied_at TEXT NOT NULL, "
            "PRIMARY KEY (version)"
            ")",
        )

    def applied_versions(self, conn: _MigrationConnection) -> set[str]:
        """Return the set of versions already recorded in ``schema_versions``."""
        self.ensure_cursor_table(conn)
        cursor = conn.execute("SELECT version FROM schema_versions")
        return {_version_of(row) for row in cursor.fetchall()}

    def run(self, conn: _MigrationConnection) -> list[str]:
        """Apply every not-yet-applied migration in order.

        Args:
            conn: An open connection (caller owns the transaction/commit).

        Returns:
            The list of versions newly applied by this call (empty on a re-run
            where everything is already present — proving idempotency).
        """
        self.ensure_cursor_table(conn)
        already = self.applied_versions(conn)
        newly_applied: list[str] = []
        for version, ddl_file in _MIGRATIONS:
            if version in already:
                continue
            self._apply_ddl(conn, ddl_file)
            self._record_version(conn, version)
            newly_applied.append(version)
        return newly_applied

    def _apply_ddl(self, conn: _MigrationConnection, ddl_file: str) -> None:
        """Execute every statement of a migration DDL file (each is idempotent)."""
        script = (self._versions_dir / ddl_file).read_text(encoding="utf-8")
        for statement in iter_sql_statements(script):
            conn.execute(statement)

    def _record_version(self, conn: _MigrationConnection, version: str) -> None:
        """Record ``version`` in the cursor (ON CONFLICT DO NOTHING — no dup)."""
        conn.execute(
            "INSERT INTO schema_versions (version, applied_at) VALUES (?, ?) "
            "ON CONFLICT (version) DO NOTHING",
            (version, now_iso()),
        )


__all__ = ["MigrationRunner"]
