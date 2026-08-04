"""Server-side strategist session lifecycle."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from agentkit.backend.auth.entities import Session
from agentkit.backend.auth.errors import AuthFailedError
from agentkit.backend.boundary.filesystem.private_files import (
    PrivateFileSecurityError,
    atomic_write_private_text,
    inspect_private_file_security,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.auth.credentials import StrategistCredentialStore

_DEFAULT_TTL = timedelta(hours=24)


class SessionStore(Protocol):
    """Strategist session lifecycle shared by middleware and auth routes."""

    def create(self, *, now: datetime | None = None) -> Session: ...

    def validate(self, session_id: str, *, now: datetime | None = None) -> Session: ...

    def revoke(self, session_id: str) -> None: ...

    def revoke_all(self) -> None: ...


class InMemorySessionStore:
    """In-memory session table with sliding 24-hour expiry."""

    def __init__(self, *, ttl: timedelta = _DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._sessions: dict[str, Session] = {}
        self._lock = RLock()

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
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def validate(self, session_id: str, *, now: datetime | None = None) -> Session:
        """Validate and slide a session expiry."""

        current_time = now or datetime.now(UTC)
        with self._lock:
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

        with self._lock:
            self._sessions.pop(session_id, None)

    def revoke_all(self) -> None:
        """Invalidate every strategist session after password rotation."""
        with self._lock:
            self._sessions.clear()


class _PersistedSession(BaseModel):
    """One session bound to the password generation that created it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session: Session
    credential_generation: str | None


class _PersistedSessions(BaseModel):
    """Closed owner-private session-table document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sessions: dict[str, _PersistedSession]


class FileSessionStore:
    """Cross-process session table shared by both Control Plane profiles."""

    def __init__(
        self,
        credential_store: StrategistCredentialStore,
        *,
        path: Path | None = None,
        ttl: timedelta = _DEFAULT_TTL,
    ) -> None:
        self._credential_store = credential_store
        self._path = path or credential_store.path.with_name(
            f"{credential_store.path.stem}.sessions{credential_store.path.suffix}",
        )
        self._ttl = ttl

    def create(self, *, now: datetime | None = None) -> Session:
        """Create and durably publish a strategist session."""
        with self._credential_store.transition_lock():
            issued_at = now or datetime.now(UTC)
            sessions = self._load_sessions(now=issued_at)
            session = Session(
                session_id=secrets.token_urlsafe(32),
                csrf_token=secrets.token_urlsafe(32),
                created_at=issued_at,
                last_activity_at=issued_at,
                expires_at=issued_at + self._ttl,
            )
            sessions[session.session_id] = _PersistedSession(
                session=session,
                credential_generation=self._credential_store.session_generation(),
            )
            self._persist_sessions(sessions)
            return session

    def validate(self, session_id: str, *, now: datetime | None = None) -> Session:
        """Validate and durably slide one session expiry."""
        with self._credential_store.transition_lock():
            current_time = now or datetime.now(UTC)
            sessions = self._load_sessions(now=current_time)
            persisted = sessions.get(session_id)
            if (
                persisted is None
                or persisted.credential_generation
                != self._credential_store.session_generation()
            ):
                sessions.pop(session_id, None)
                self._persist_sessions(sessions)
                raise AuthFailedError("Authentication failed")
            session = persisted.session
            refreshed = session.model_copy(
                update={
                    "last_activity_at": current_time,
                    "expires_at": current_time + self._ttl,
                },
            )
            sessions[session_id] = persisted.model_copy(update={"session": refreshed})
            self._persist_sessions(sessions)
            return refreshed

    def revoke(self, session_id: str) -> None:
        """Durably invalidate one session id."""
        with self._credential_store.transition_lock():
            sessions = self._load_sessions(now=datetime.now(UTC))
            sessions.pop(session_id, None)
            self._persist_sessions(sessions)

    def revoke_all(self) -> None:
        """Durably invalidate all sessions across every listener profile."""
        with self._credential_store.transition_lock():
            self._persist_sessions({})

    def _load_sessions(self, *, now: datetime) -> dict[str, _PersistedSession]:
        if not self._path.exists():
            return {}
        document = self._read_validated_sessions()
        if document is None:
            raise AuthFailedError("Authentication failed")
        return {
            session_id: persisted
            for session_id, persisted in document.sessions.items()
            if persisted.session.expires_at > now
        }

    def _read_validated_sessions(self) -> _PersistedSessions | None:
        """Read secret-bearing sessions without retaining parser exceptions."""
        try:
            if not inspect_private_file_security(self._path).owner_only:
                return None
            return _PersistedSessions.model_validate_json(
                self._path.read_text(encoding="utf-8"),
            )
        except (OSError, ValidationError, PrivateFileSecurityError):
            return None

    def _persist_sessions(self, sessions: dict[str, _PersistedSession]) -> None:
        document = _PersistedSessions(sessions=sessions)
        atomic_write_private_text(self._path, document.model_dump_json())


__all__ = ["FileSessionStore", "InMemorySessionStore", "SessionStore"]
