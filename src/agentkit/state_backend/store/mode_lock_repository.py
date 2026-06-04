"""ModeLockRepository — canonical ``project_mode_lock`` persistence (FK-24 §24.3.3).

The projektweite Control-Plane Mode-Lock (FK-24 §24.3.3 / story-lifecycle.A8)
enforces the Fast/Standard mutual exclusion: while any Standard story is
``In Progress`` no Fast story may start, and vice versa.

Scope (AG3-034 §2.1.2 / §2.2):
- This adapter establishes only the **read path** consumed by Preflight
  Check 10 (``no_competing_story_mode_active``).  The atomic mode-lock
  *set* on story start is AG3-018 / a follow-up story.  ``set_lock`` exists
  here purely so tests (and a future writer) can seed the table; it is a
  plain upsert, not the atomic acquire/release protocol of FK-24 §24.3.3.

Architecture (mirrors ``freeze_repository.py`` / ``lock_record_repository.py``):
- Postgres is canonical (DK-05 §5); SQLite is the test-only parallel path
  (``AGENTKIT_ALLOW_SQLITE=1``).
- Does NOT import from ``agentkit.state_backend.store.facade``.
- Schema (``project_mode_lock``) lives in both ``postgres_schema.sql``
  (canonical) and ``sqlite_store.py`` (test-parallel); this adapter only
  reads/writes via the bootstrapped schema.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Allowed ``active_mode`` wire values (mirrors the DDL CHECK constraint).
#: The mode-lock lives on the DECOUPLED fast/standard ``mode`` axis
#: (``WireStoryMode``, FK-24 §24.3.3) — NOT the ``execution_route`` axis.  The
#: earlier ``{execution, exploration, fast}`` set mixed both axes (the axis
#: bug); ``StoryContext.mode`` only ever holds ``standard``/``fast``.
ACTIVE_MODE_VALUES: frozenset[str] = frozenset({"standard", "fast"})


@dataclass(frozen=True)
class ModeLockRecord:
    """A persisted project mode-lock record (FK-24 §24.3.3).

    Attributes:
        project_key: Owning project key (primary key).
        active_mode: The currently held fast/standard ``mode`` (``"standard"``
            / ``"fast"``, the decoupled ``WireStoryMode`` axis, FK-24 §24.3.3),
            or ``None`` when the lock is idle.
        holder_count: Number of active stories holding the lock.
        updated_at: ISO-8601 timestamp of the last mutation.
    """

    project_key: str
    active_mode: str | None
    holder_count: int
    updated_at: str


# ---------------------------------------------------------------------------
# Backend detection (identical pattern to freeze_repository)
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    return os.environ.get("AGENTKIT_STATE_BACKEND", "sqlite").lower() == "postgres"


def _assert_sqlite_allowed() -> None:
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


def _sqlite_db_path(store_dir: Path) -> Path:
    from agentkit.state_backend.config import versioned_sqlite_db_file
    from agentkit.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    from agentkit.state_backend import sqlite_store

    _assert_sqlite_allowed()
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # SINGLE SOURCE OF TRUTH: bootstrap the full canonical schema so
    # project_mode_lock exists (DDL owned by sqlite_store, AG3-034).
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

    from agentkit.state_backend.schema_bootstrap import ensure_versioned_schema

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


_SQLITE_UPSERT = """
    INSERT INTO project_mode_lock (
        project_key, active_mode, holder_count, updated_at
    ) VALUES (
        :project_key, :active_mode, :holder_count, :updated_at
    )
    ON CONFLICT (project_key) DO UPDATE SET
        active_mode = excluded.active_mode,
        holder_count = excluded.holder_count,
        updated_at = excluded.updated_at
"""

_PG_UPSERT = """
    INSERT INTO project_mode_lock (
        project_key, active_mode, holder_count, updated_at
    ) VALUES (
        %(project_key)s, %(active_mode)s, %(holder_count)s, %(updated_at)s
    )
    ON CONFLICT (project_key) DO UPDATE SET
        active_mode = excluded.active_mode,
        holder_count = excluded.holder_count,
        updated_at = excluded.updated_at
"""


class ModeLockRepository:
    """Canonical persistence adapter for ``project_mode_lock`` (FK-24 §24.3.3).

    Args:
        store_dir: Base directory for the SQLite state store. Ignored for
            Postgres.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    def read_lock(self, project_key: str) -> ModeLockRecord | None:
        """Return the project mode-lock record for ``project_key``, or ``None``.

        Read path consumed by Preflight Check 10 (AG3-034 §2.1.2).  A missing
        row means the lock is idle (no active mode) for that project.

        Args:
            project_key: Project key to look up.

        Returns:
            The persisted :class:`ModeLockRecord`, or ``None`` when absent.
        """
        if _is_postgres():
            return self._pg_read(project_key)
        return self._sqlite_read(project_key)

    def set_lock(
        self,
        project_key: str,
        *,
        active_mode: str | None,
        holder_count: int,
        updated_at: str,
    ) -> ModeLockRecord:
        """Upsert the mode-lock row (test/seed helper, NOT the atomic protocol).

        The atomic acquire/release on story start/close is AG3-018 / a
        follow-up story (story.md §2.2).  This is a plain upsert so the read
        path can be exercised; it performs no holder-count arithmetic.

        Args:
            project_key: Project key.
            active_mode: Held mode, or ``None`` for idle.  Must be one of
                :data:`ACTIVE_MODE_VALUES` when not ``None``.
            holder_count: Number of holders (``>= 0``).
            updated_at: ISO-8601 timestamp.

        Returns:
            The persisted :class:`ModeLockRecord`.

        Raises:
            ValueError: When ``active_mode`` is not a recognised value or
                ``holder_count`` is negative.
        """
        if active_mode is not None and active_mode not in ACTIVE_MODE_VALUES:
            raise ValueError(
                f"active_mode {active_mode!r} must be one of "
                f"{sorted(ACTIVE_MODE_VALUES)} or None"
            )
        if holder_count < 0:
            raise ValueError(f"holder_count must be >= 0, got {holder_count}")
        row = {
            "project_key": project_key,
            "active_mode": active_mode,
            "holder_count": holder_count,
            "updated_at": updated_at,
        }
        if _is_postgres():
            with _postgres_connect() as conn:
                conn.execute(_PG_UPSERT, row)
        else:
            with _sqlite_connect(self._store_dir) as conn:
                conn.execute(_SQLITE_UPSERT, row)
        return ModeLockRecord(
            project_key=project_key,
            active_mode=active_mode,
            holder_count=holder_count,
            updated_at=updated_at,
        )

    def _sqlite_read(self, project_key: str) -> ModeLockRecord | None:
        with _sqlite_connect(self._store_dir) as conn:
            row = conn.execute(
                "SELECT * FROM project_mode_lock WHERE project_key=?",
                (project_key,),
            ).fetchone()
        return _row_to_record(dict(row)) if row is not None else None

    def _pg_read(self, project_key: str) -> ModeLockRecord | None:
        with _postgres_connect() as conn:
            row = conn.execute(
                "SELECT * FROM project_mode_lock WHERE project_key=%s",
                (project_key,),
            ).fetchone()
        return _row_to_record(dict(row)) if row is not None else None


def _row_to_record(row: dict[str, Any]) -> ModeLockRecord:
    raw_mode = row.get("active_mode")
    return ModeLockRecord(
        project_key=str(row["project_key"]),
        active_mode=str(raw_mode) if raw_mode is not None else None,
        holder_count=int(row["holder_count"]),
        updated_at=str(row["updated_at"]),
    )


__all__ = ["ACTIVE_MODE_VALUES", "ModeLockRecord", "ModeLockRepository"]
