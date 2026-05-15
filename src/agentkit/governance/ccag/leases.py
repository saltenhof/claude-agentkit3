"""Permission-Lease — befristete Einzelfall-Freigabe (consume-once).

A PermissionLease is a single-use approval for one specific tool invocation.
After the first successful ``consume()``, the lease is exhausted and all
subsequent consume calls raise ``LeaseExhaustedError``.

Leases live in an in-process SQLite store (via the standard state_backend
driver) keyed by ``lease_id``.  They are session-scoped: a restart clears
all leases unless the same DB path is shared across sessions.

Design decision: Leases are stored in a dedicated SQLite table
``ccag_permission_leases`` in the per-story state DB (``state_backend_dir``).
This avoids raw JSON files and follows the state_backend repository pattern
established in AK3.

FK-42 scope reference: §42.2 (consume-once lease semantics implied by the
one-shot approval model), story.md Akzeptanzkriterium 3.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


class PermissionLease(BaseModel):
    """A single-use permission for one tool invocation.

    Attributes:
        lease_id: Unique identifier for this lease.
        tool_name: The tool that was pre-approved.
        tool_input_fingerprint: A string fingerprint of the tool input (for audit).
        granted_at: ISO-8601 timestamp when the lease was created.
        expires_at: ISO-8601 timestamp after which the lease is invalid even
            if not yet consumed (``None`` → no expiry).
        consumed: True after the first successful ``consume()`` call.
        story_id: Optional story context for audit purposes.
    """

    model_config = ConfigDict(frozen=False)

    lease_id: str
    tool_name: str
    tool_input_fingerprint: str = ""
    granted_at: str
    expires_at: str | None = None
    consumed: bool = False
    story_id: str = ""


class LeaseExhaustedError(RuntimeError):
    """Raised when a consume-once lease has already been consumed."""


class LeaseExpiredError(RuntimeError):
    """Raised when a lease has passed its expiry timestamp."""


class LeaseNotFoundError(KeyError):
    """Raised when a lease_id is not found in the store."""


# ---------------------------------------------------------------------------
# SQLite store for leases
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ccag_permission_leases (
    lease_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    tool_input_fingerprint TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    expires_at TEXT,
    consumed INTEGER NOT NULL DEFAULT 0,
    story_id TEXT NOT NULL DEFAULT ''
);
"""

_lock = threading.Lock()


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_lease(row: sqlite3.Row) -> PermissionLease:
    return PermissionLease(
        lease_id=str(row["lease_id"]),
        tool_name=str(row["tool_name"]),
        tool_input_fingerprint=str(row["tool_input_fingerprint"]),
        granted_at=str(row["granted_at"]),
        expires_at=row["expires_at"],
        consumed=bool(row["consumed"]),
        story_id=str(row["story_id"]),
    )


class PermissionLeaseStore:
    """Thread-safe SQLite-backed store for permission leases.

    Stores consume-once leases in a dedicated table.  The DB path is
    determined by the caller; in production it is the per-story state DB.
    For tests, pass a ``tmp_path``-relative path.

    Args:
        db_path: Path to the SQLite database file.  Created if missing.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def save(self, lease: PermissionLease) -> None:
        """Persist a new lease.  Overwrites if lease_id already exists.

        Args:
            lease: The :class:`PermissionLease` to persist.
        """
        with _lock, _connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ccag_permission_leases
                    (lease_id, tool_name, tool_input_fingerprint,
                     granted_at, expires_at, consumed, story_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lease.lease_id,
                    lease.tool_name,
                    lease.tool_input_fingerprint,
                    lease.granted_at,
                    lease.expires_at,
                    int(lease.consumed),
                    lease.story_id,
                ),
            )

    def load(self, lease_id: str) -> PermissionLease:
        """Load a lease by ID.

        Args:
            lease_id: Unique lease identifier.

        Returns:
            The :class:`PermissionLease`.

        Raises:
            LeaseNotFoundError: When no lease with this ID exists.
        """
        with _connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM ccag_permission_leases WHERE lease_id = ?",
                (lease_id,),
            ).fetchone()
        if row is None:
            raise LeaseNotFoundError(f"No lease with id={lease_id!r}")
        return _row_to_lease(row)

    def consume(self, lease_id: str) -> PermissionLease:
        """Consume a lease atomically (consume-once semantics).

        On first call: marks the lease as consumed and returns it.
        On subsequent calls: raises :class:`LeaseExhaustedError`.
        After expiry: raises :class:`LeaseExpiredError`.

        Args:
            lease_id: Unique lease identifier.

        Returns:
            The consumed :class:`PermissionLease`.

        Raises:
            LeaseNotFoundError: When no lease with this ID exists.
            LeaseExhaustedError: When the lease was already consumed.
            LeaseExpiredError: When the lease has passed its expiry time.
        """
        with _lock, _connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM ccag_permission_leases WHERE lease_id = ?",
                (lease_id,),
            ).fetchone()
            if row is None:
                raise LeaseNotFoundError(f"No lease with id={lease_id!r}")
            lease = _row_to_lease(row)

            if lease.consumed:
                raise LeaseExhaustedError(
                    f"Lease {lease_id!r} has already been consumed (consume-once)"
                )

            if lease.expires_at is not None:
                now_utc = datetime.now(tz=UTC)
                try:
                    expiry = datetime.fromisoformat(lease.expires_at)
                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=UTC)
                    if now_utc > expiry:
                        raise LeaseExpiredError(
                            f"Lease {lease_id!r} expired at {lease.expires_at}"
                        )
                except ValueError:
                    pass  # unparseable expiry → treat as non-expiring

            conn.execute(
                "UPDATE ccag_permission_leases SET consumed = 1 WHERE lease_id = ?",
                (lease_id,),
            )
            lease.consumed = True
            return lease

    def is_valid(self, lease_id: str) -> bool:
        """Return True when a lease exists, is not consumed, and is not expired.

        Args:
            lease_id: Unique lease identifier.

        Returns:
            True when the lease can still be consumed.
        """
        try:
            lease = self.load(lease_id)
        except LeaseNotFoundError:
            return False
        if lease.consumed:
            return False
        if lease.expires_at is not None:
            now_utc = datetime.now(tz=UTC)
            try:
                expiry = datetime.fromisoformat(lease.expires_at)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=UTC)
                if now_utc > expiry:
                    return False
            except ValueError:
                pass
        return True


__all__ = [
    "LeaseExhaustedError",
    "LeaseExpiredError",
    "LeaseNotFoundError",
    "PermissionLease",
    "PermissionLeaseStore",
]
