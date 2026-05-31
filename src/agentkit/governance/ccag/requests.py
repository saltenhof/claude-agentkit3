"""Permission-Request — blockiert Tool-Call, setzt Run auf PAUSED.

When the CCAG runtime encounters an unknown permission in ``story_execution``
mode (FK-42 §42.2.5), it cannot invoke a host prompt dialog.  Instead it
creates a PermissionRequest that:

1. Is stored in the state-backend (SQLite) so the Frontend Permission-Inbox
   (future story) can surface it to the human.
2. Returns ``unknown_permission`` to the caller so the harness adapter can
   exit with code 2 (block) and print an explanatory message.
3. Has a TTL (``expires_at``).  When the TTL elapses without a human decision,
   the request is implicitly DENIED.

Akzeptanzkriterium 2: "erscheint im State-Backend" — fulfilled by
:class:`PermissionRequestStore` writing to a dedicated SQLite table.

FK-42 §42.2.5 reference: mode-scharfe Entscheidung in story_execution.
Frontend-UI is out-of-scope for AG3-013 (reserved for follow-up story).
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

RequestStatus = Literal["pending", "approved", "denied", "expired"]

#: Default TTL in seconds for a permission request (10 minutes).
DEFAULT_TTL_SECONDS: int = 600


class PermissionRequest(BaseModel):
    """A pending permission request for a tool invocation in story_execution mode.

    Attributes:
        request_id: Unique identifier.
        tool_name: The tool whose invocation is pending approval.
        tool_input_fingerprint: Serialised representation of tool input (for display).
        story_id: Story context.
        run_id: Run context (for state-backend keying).
        operating_mode: Operating mode that triggered the request (always ``story_execution``).
        status: One of ``pending``, ``approved``, ``denied``, ``expired``.
        created_at: ISO-8601 timestamp of creation.
        expires_at: ISO-8601 timestamp after which the request auto-denies.
        decided_at: ISO-8601 timestamp when a human made a decision (``None`` if pending).
        decision_note: Optional human note explaining the decision.
    """

    model_config = ConfigDict(frozen=False)

    request_id: str
    tool_name: str
    tool_input_fingerprint: str = ""
    story_id: str = ""
    run_id: str = ""
    operating_mode: str = "story_execution"
    status: RequestStatus = "pending"
    created_at: str
    expires_at: str
    decided_at: str | None = None
    decision_note: str = ""

    def is_expired(self) -> bool:
        """Return True when the request has passed its expiry timestamp.

        Returns:
            True when now > expires_at (UTC comparison).
        """
        now_utc = datetime.now(tz=UTC)
        try:
            expiry = datetime.fromisoformat(self.expires_at)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            return now_utc > expiry
        except ValueError:
            return False

    def effective_status(self) -> RequestStatus:
        """Return the effective status, accounting for TTL expiry.

        Returns:
            ``"expired"`` when pending and past expiry, otherwise the stored status.
        """
        if self.status == "pending" and self.is_expired():
            return "expired"
        return self.status


# ---------------------------------------------------------------------------
# SQLite store for permission requests
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ccag_permission_requests (
    request_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    tool_input_fingerprint TEXT NOT NULL,
    story_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    operating_mode TEXT NOT NULL DEFAULT 'story_execution',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    decided_at TEXT,
    decision_note TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ccag_permission_requests_story_idx
    ON ccag_permission_requests (story_id, status);
"""

_lock = threading.Lock()


def _assert_sqlite_allowed() -> None:
    """Raise RuntimeError if SQLite backend is not explicitly enabled.

    Enforces the AGENTKIT_ALLOW_SQLITE=1 gating pattern (Fix E8, AG3-031 Pass-6).
    Delegates to the config-foundation gate so this A-type governance module
    does not import the T-type state-backend driver boundary (AC011).
    """
    from agentkit.config.sqlite_gate import assert_sqlite_allowed

    assert_sqlite_allowed()


@contextmanager
def _connect(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _assert_sqlite_allowed()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_request(row: sqlite3.Row) -> PermissionRequest:
    return PermissionRequest(
        request_id=str(row["request_id"]),
        tool_name=str(row["tool_name"]),
        tool_input_fingerprint=str(row["tool_input_fingerprint"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        operating_mode=str(row["operating_mode"]),
        status=row["status"],
        created_at=str(row["created_at"]),
        expires_at=str(row["expires_at"]),
        decided_at=row["decided_at"],
        decision_note=str(row["decision_note"]),
    )


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _expiry_iso(ttl_seconds: int) -> str:
    return (
        datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds)
    ).isoformat()


class PermissionRequestStore:
    """Thread-safe SQLite-backed store for permission requests.

    Creates requests that block a tool call until a human decides (or the
    TTL expires, causing automatic DENIED).

    Args:
        db_path: Path to the SQLite database file.  Created if missing.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def create(
        self,
        *,
        request_id: str,
        tool_name: str,
        tool_input_fingerprint: str = "",
        story_id: str = "",
        run_id: str = "",
        operating_mode: str = "story_execution",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> PermissionRequest:
        """Create and persist a new pending permission request.

        Args:
            request_id: Unique identifier (caller must ensure uniqueness).
            tool_name: The tool whose call is being blocked.
            tool_input_fingerprint: Serialised tool input for human review.
            story_id: Story context.
            run_id: Run context.
            operating_mode: Operating mode (typically ``"story_execution"``).
            ttl_seconds: Seconds until automatic expiry → DENIED.

        Returns:
            The created :class:`PermissionRequest`.
        """
        now = _now_iso()
        expiry = _expiry_iso(ttl_seconds)
        req = PermissionRequest(
            request_id=request_id,
            tool_name=tool_name,
            tool_input_fingerprint=tool_input_fingerprint,
            story_id=story_id,
            run_id=run_id,
            operating_mode=operating_mode,
            status="pending",
            created_at=now,
            expires_at=expiry,
        )
        with _lock, _connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ccag_permission_requests
                    (request_id, tool_name, tool_input_fingerprint,
                     story_id, run_id, operating_mode, status,
                     created_at, expires_at, decided_at, decision_note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.request_id,
                    req.tool_name,
                    req.tool_input_fingerprint,
                    req.story_id,
                    req.run_id,
                    req.operating_mode,
                    req.status,
                    req.created_at,
                    req.expires_at,
                    req.decided_at,
                    req.decision_note,
                ),
            )
        return req

    def load(self, request_id: str) -> PermissionRequest | None:
        """Load a request by ID.

        Args:
            request_id: Unique request identifier.

        Returns:
            The :class:`PermissionRequest`, or ``None`` if not found.
        """
        with _connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM ccag_permission_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_request(row)

    def list_pending(
        self,
        *,
        story_id: str | None = None,
    ) -> list[PermissionRequest]:
        """List pending requests, optionally filtered by story.

        Args:
            story_id: When given, restrict to requests for this story.

        Returns:
            List of pending :class:`PermissionRequest` instances.
        """
        with _connect(self._db_path) as conn:
            if story_id is not None:
                rows = conn.execute(
                    "SELECT * FROM ccag_permission_requests WHERE status = 'pending' AND story_id = ?",
                    (story_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM ccag_permission_requests WHERE status = 'pending'",
                ).fetchall()
        return [_row_to_request(r) for r in rows]

    def decide(
        self,
        request_id: str,
        *,
        approved: bool,
        note: str = "",
    ) -> PermissionRequest | None:
        """Record a human decision on a pending request.

        Args:
            request_id: Unique request identifier.
            approved: True → ``approved``, False → ``denied``.
            note: Optional human note.

        Returns:
            The updated :class:`PermissionRequest`, or ``None`` if not found.
        """
        new_status: RequestStatus = "approved" if approved else "denied"
        now = _now_iso()
        with _lock, _connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE ccag_permission_requests
                SET status = ?, decided_at = ?, decision_note = ?
                WHERE request_id = ? AND status = 'pending'
                """,
                (new_status, now, note, request_id),
            )
            row = conn.execute(
                "SELECT * FROM ccag_permission_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_request(row)


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "PermissionRequest",
    "PermissionRequestStore",
    "RequestStatus",
]
