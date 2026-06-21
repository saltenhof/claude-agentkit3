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
- Does NOT import from ``agentkit.backend.state_backend.store.facade``.
- Schema (``project_mode_lock``) lives in both ``postgres_schema.sql``
  (canonical) and ``sqlite_store.py`` (test-parallel); this adapter only
  reads/writes via the bootstrapped schema.
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.backend.governance.errors import ModeLockConflictError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    #: Decide ``(active_mode, holder_count)`` from the current ``(mode, count)``.
    _LockTransition = Callable[
        [tuple[str | None, int]], tuple[str | None, int]
    ]

#: Allowed ``active_mode`` wire values (mirrors the DDL CHECK constraint).
#: The mode-lock lives on the DECOUPLED fast/standard ``mode`` axis
#: (``WireStoryMode``, FK-24 §24.3.3) — NOT the ``execution_route`` axis.  The
#: earlier ``{execution, exploration, fast}`` set mixed both axes (the axis
#: bug); ``StoryContext.mode`` only ever holds ``standard``/``fast``.
ACTIVE_MODE_VALUES: frozenset[str] = frozenset({"standard", "fast"})

#: SQLite is the test-only parallel path; under real multi-connection thread
#: contention a concurrent ``BEGIN IMMEDIATE`` / WAL transition can still surface
#: SQLITE_BUSY ("database is locked") even with ``busy_timeout`` set. The atomic
#: CAS retries the whole read-decide-write a bounded number of times on that
#: transient busy error (a clean ``ModeLockConflictError`` is NEVER retried).
#: Postgres (canonical, DK-05 §5) serialises via ``pg_advisory_xact_lock`` instead.
_SQLITE_BUSY_RETRIES = 12
_SQLITE_BUSY_BACKOFF_SECONDS = 0.025


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
    # FIX-2: a concurrent ``BEGIN IMMEDIATE`` must WAIT for the in-flight writer to
    # commit rather than fail immediately with "database is locked" (the default
    # busy timeout is 0). 5s is ample for the tiny read-decide-write CAS.
    conn.execute("PRAGMA busy_timeout = 5000")
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

    def acquire(self, project_key: str, mode: str) -> ModeLockRecord:
        """Atomically acquire the project mode-lock for ``mode`` (FK-24 §24.3.3).

        The enforcement half of the Fast/Standard between-modes mutex, run at
        story START for ALL stories (standard AND fast). ATOMIC (transactional /
        CAS, not a plain upsert):

        * lock idle (no row / ``holder_count == 0`` / ``active_mode is None``)
          => set ``active_mode = mode``, ``holder_count = 1``;
        * same mode already held => increment ``holder_count``;
        * OPPOSITE mode held => fail closed with :class:`ModeLockConflictError`
          (the last-writer guard behind Preflight Check 10).

        Args:
            project_key: Owning project key.
            mode: The acquiring story's fast/standard ``mode`` (``"standard"`` /
                ``"fast"`` — the decoupled ``WireStoryMode`` axis).

        Returns:
            The persisted :class:`ModeLockRecord` after the acquire.

        Raises:
            ValueError: When ``mode`` is not a recognised value.
            ModeLockConflictError: When the opposite mode is currently held.
        """
        if mode not in ACTIVE_MODE_VALUES:
            raise ValueError(
                f"mode {mode!r} must be one of {sorted(ACTIVE_MODE_VALUES)}"
            )
        return self._mutate(project_key, lambda current: _acquire_next(current, mode))

    def release(self, project_key: str, mode: str) -> ModeLockRecord:
        """Atomically release one holder of the project mode-lock (FK-24 §24.3.3).

        The release half of the mutex, run at story CLOSE (and cancel/reset).
        ATOMIC: decrements ``holder_count``; when it reaches ``0`` the lock
        resets to idle (``active_mode = None``). Idempotent / fail-safe for an
        over-release: an already-idle lock (no row / ``holder_count == 0``)
        stays idle (a story that never acquired must not drive the count
        negative — recovery/resume safety).

        Args:
            project_key: Owning project key.
            mode: The releasing story's mode (validated against the held mode
                when one is present; a mismatch is a no-op idle-safe release —
                the holder it would decrement is not this mode).

        Returns:
            The persisted :class:`ModeLockRecord` after the release.

        Raises:
            ValueError: When ``mode`` is not a recognised value.
        """
        if mode not in ACTIVE_MODE_VALUES:
            raise ValueError(
                f"mode {mode!r} must be one of {sorted(ACTIVE_MODE_VALUES)}"
            )
        return self._mutate(project_key, lambda current: _release_next(current, mode))

    def _mutate(
        self,
        project_key: str,
        decide: _LockTransition,
    ) -> ModeLockRecord:
        """Run an atomic read-decide-write of the mode-lock row (CAS, single tx)."""
        if _is_postgres():
            return self._pg_mutate(project_key, decide)
        return self._sqlite_mutate(project_key, decide)

    def _sqlite_mutate(
        self, project_key: str, decide: _LockTransition
    ) -> ModeLockRecord:
        """Race-safe SQLite CAS with bounded SQLITE_BUSY retry (FIX-2).

        ``busy_timeout`` covers most contention, but a concurrent WAL transition /
        ``BEGIN IMMEDIATE`` can still raise SQLITE_BUSY; retry the whole
        read-decide-write on "database is locked". A ``ModeLockConflictError``
        (the legitimate opposite-mode decision) is NOT a busy error and propagates
        immediately — it is never retried.
        """
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(_SQLITE_BUSY_RETRIES):
            try:
                return self._sqlite_mutate_once(project_key, decide)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                last_error = exc
                backoff_multiplier = attempt + 1
                backoff_seconds = _SQLITE_BUSY_BACKOFF_SECONDS * backoff_multiplier
                time.sleep(backoff_seconds)
        if last_error is not None:
            raise last_error
        raise RuntimeError("mode-lock CAS retry loop did not execute")

    def _sqlite_mutate_once(
        self, project_key: str, decide: _LockTransition
    ) -> ModeLockRecord:
        with _sqlite_connect(self._store_dir) as conn:
            # FIX-2 (race-safe CAS): a plain deferred transaction lets two
            # concurrent acquirers BOTH read the (missing) row before either
            # writes, so two opposite-mode first-acquires would both pass. Issue
            # ``BEGIN IMMEDIATE`` so a RESERVED write lock is taken BEFORE the
            # read-decide-write: the second connection blocks here until the first
            # commits and then reads the post-acquire row, so the opposite-mode
            # decision sees the held mode and fails closed. ``isolation_level`` is
            # cleared so sqlite3 does not start its own implicit transaction that
            # would conflict with this explicit ``BEGIN``.
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT active_mode, holder_count FROM project_mode_lock "
                    "WHERE project_key=?",
                    (project_key,),
                ).fetchone()
                current = _current_from_row(dict(row) if row is not None else None)
                active_mode, holder_count = decide(current)
                updated_at = _now_iso()
                conn.execute(
                    _SQLITE_UPSERT,
                    {
                        "project_key": project_key,
                        "active_mode": active_mode,
                        "holder_count": holder_count,
                        "updated_at": updated_at,
                    },
                )
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return ModeLockRecord(
            project_key=project_key,
            active_mode=active_mode,
            holder_count=holder_count,
            updated_at=updated_at,
        )

    def _pg_mutate(
        self, project_key: str, decide: _LockTransition
    ) -> ModeLockRecord:
        with _postgres_connect() as conn:
            # FIX-2 (race-safe CAS): ``SELECT ... FOR UPDATE`` does NOT lock a
            # MISSING row, so two concurrent first-acquires on a project with no
            # row would both read "idle" and both write -> two opposite modes
            # acquired. Take a transaction-scoped ADVISORY lock keyed on the
            # ``project_key`` FIRST: it serialises the whole read-decide-write per
            # project even when the row does not yet exist (it is held until the
            # tx commits/rolls back). The later ``FOR UPDATE`` then row-locks the
            # now-existing row for good measure.
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"project_mode_lock:{project_key}",),
            )
            row = conn.execute(
                "SELECT active_mode, holder_count FROM project_mode_lock "
                "WHERE project_key=%s FOR UPDATE",
                (project_key,),
            ).fetchone()
            current = _current_from_row(dict(row) if row is not None else None)
            active_mode, holder_count = decide(current)
            updated_at = _now_iso()
            conn.execute(
                _PG_UPSERT,
                {
                    "project_key": project_key,
                    "active_mode": active_mode,
                    "holder_count": holder_count,
                    "updated_at": updated_at,
                },
            )
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


def _now_iso() -> str:
    """Return the current UTC instant as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _current_from_row(row: dict[str, Any] | None) -> tuple[str | None, int]:
    """Normalise a raw row into ``(active_mode, holder_count)`` (idle when absent)."""
    if row is None:
        return (None, 0)
    raw_mode = row.get("active_mode")
    active_mode = str(raw_mode) if raw_mode is not None else None
    holder_count = int(row.get("holder_count") or 0)
    if holder_count <= 0:
        return (None, holder_count if holder_count > 0 else 0)
    return (active_mode, holder_count)


def _acquire_next(
    current: tuple[str | None, int], mode: str
) -> tuple[str | None, int]:
    """Compute the post-acquire ``(active_mode, holder_count)`` (FK-24 §24.3.3).

    Idle / same-mode -> hold ``mode`` and increment; opposite mode -> fail closed.
    """
    active_mode, holder_count = current
    if active_mode is None or holder_count <= 0:
        return (mode, 1)
    if active_mode == mode:
        return (mode, holder_count + 1)
    raise ModeLockConflictError(
        f"cannot acquire mode {mode!r}: project holds the opposite mode "
        f"{active_mode!r} ({holder_count} holder(s)); Fast and Standard are "
        "mutually exclusive (FK-24 §24.3.3)"
    )


def _release_next(
    current: tuple[str | None, int], mode: str
) -> tuple[str | None, int]:
    """Compute the post-release ``(active_mode, holder_count)`` (FK-24 §24.3.3).

    Decrement the holder count; reset to idle (``None``, ``0``) at zero. An
    already-idle lock, or a release of a mode that is not the one held, is an
    idle-safe no-op (over-release / double-release on resume must not drive the
    count negative).
    """
    active_mode, holder_count = current
    if active_mode is None or holder_count <= 0 or active_mode != mode:
        return (active_mode if holder_count > 0 else None, max(holder_count, 0))
    next_count = holder_count - 1
    if next_count <= 0:
        return (None, 0)
    return (active_mode, next_count)


def _row_to_record(row: dict[str, Any]) -> ModeLockRecord:
    raw_mode = row.get("active_mode")
    return ModeLockRecord(
        project_key=str(row["project_key"]),
        active_mode=str(raw_mode) if raw_mode is not None else None,
        holder_count=int(row["holder_count"]),
        updated_at=str(row["updated_at"]),
    )


__all__ = [
    "ACTIVE_MODE_VALUES",
    "ModeLockConflictError",
    "ModeLockRecord",
    "ModeLockRepository",
]
