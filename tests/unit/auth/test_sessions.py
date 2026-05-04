from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agentkit.auth.errors import AuthFailedError
from agentkit.auth.sessions import InMemorySessionStore


def test_session_validation_slides_expiry() -> None:
    store = InMemorySessionStore(ttl=timedelta(hours=24))
    issued_at = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
    session = store.create(now=issued_at)

    refreshed = store.validate(
        session.session_id,
        now=issued_at + timedelta(hours=1),
    )

    assert refreshed.session_id == session.session_id
    assert refreshed.expires_at == issued_at + timedelta(hours=25)


def test_expired_session_is_rejected() -> None:
    store = InMemorySessionStore(ttl=timedelta(seconds=1))
    issued_at = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
    session = store.create(now=issued_at)

    with pytest.raises(AuthFailedError):
        store.validate(session.session_id, now=issued_at + timedelta(seconds=2))
