"""Server-side strategist session lifecycle."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from agentkit.auth.entities import Session
from agentkit.auth.errors import AuthFailedError

_DEFAULT_TTL = timedelta(hours=24)


class InMemorySessionStore:
    """In-memory session table with sliding 24-hour expiry."""

    def __init__(self, *, ttl: timedelta = _DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._sessions: dict[str, Session] = {}

    def create(self, *, now: datetime | None = None) -> Session:
        """Create a new strategist session."""

        issued_at = now or datetime.now(UTC)
        session = Session(
            session_id=secrets.token_urlsafe(32),
            csrf_token=secrets.token_urlsafe(32),
            created_at=issued_at,
            last_activity_at=issued_at,
            expires_at=issued_at + self._ttl,
        )
        self._sessions[session.session_id] = session
        return session

    def validate(self, session_id: str, *, now: datetime | None = None) -> Session:
        """Validate and slide a session expiry."""

        current_time = now or datetime.now(UTC)
        session = self._sessions.get(session_id)
        if session is None or session.expires_at <= current_time:
            self._sessions.pop(session_id, None)
            raise AuthFailedError("Authentication failed")
        refreshed = session.model_copy(
            update={
                "last_activity_at": current_time,
                "expires_at": current_time + self._ttl,
            },
        )
        self._sessions[session_id] = refreshed
        return refreshed

    def revoke(self, session_id: str) -> None:
        """Invalidate one session id."""

        self._sessions.pop(session_id, None)
