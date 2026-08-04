from __future__ import annotations

import json
import traceback
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.auth.credentials import StrategistCredentialStore
from agentkit.backend.auth.entities import Session
from agentkit.backend.auth.errors import AuthFailedError
from agentkit.backend.auth.sessions import FileSessionStore, InMemorySessionStore
from agentkit.backend.boundary.filesystem.private_files import atomic_write_private_text

if TYPE_CHECKING:
    from pathlib import Path


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


def test_parallel_validation_cannot_resurrect_a_revoked_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemorySessionStore()
    session = store.create()
    validation_entered = Event()
    allow_validation = Event()
    revocation_finished = Event()
    original_model_copy = Session.model_copy

    def paused_model_copy(self: Session, *args: object, **kwargs: object) -> Session:
        validation_entered.set()
        assert allow_validation.wait(timeout=5)
        return original_model_copy(self, *args, **kwargs)

    monkeypatch.setattr(Session, "model_copy", paused_model_copy)
    validation = Thread(target=store.validate, args=(session.session_id,))
    revocation = Thread(
        target=lambda: (store.revoke_all(), revocation_finished.set()),
    )
    validation.start()
    assert validation_entered.wait(timeout=5)
    revocation.start()
    revocation_was_blocked = not revocation_finished.wait(timeout=0.1)
    allow_validation.set()
    validation.join(timeout=5)
    revocation.join(timeout=5)
    assert not validation.is_alive()
    assert not revocation.is_alive()
    assert revocation_was_blocked

    with pytest.raises(AuthFailedError):
        store.validate(session.session_id)


def test_file_session_store_shares_revocation_across_profile_instances(
    tmp_path: Path,
) -> None:
    credential_path = tmp_path / "auth.json"
    first_credentials = StrategistCredentialStore(credential_path)
    first_credentials.initialize_password("secret")
    first_profile = FileSessionStore(first_credentials)
    second_profile = FileSessionStore(StrategistCredentialStore(credential_path))
    session = first_profile.create()

    assert second_profile.validate(session.session_id).session_id == session.session_id
    second_profile.revoke_all()

    with pytest.raises(AuthFailedError):
        first_profile.validate(session.session_id)


def test_file_session_generation_rejects_old_session_without_cleanup(
    tmp_path: Path,
) -> None:
    credential_path = tmp_path / "auth.json"
    credentials = StrategistCredentialStore(credential_path)
    credentials.initialize_password("secret")
    sessions = FileSessionStore(credentials)
    session = sessions.create()

    credentials.rotate_password("replacement", op_id="op-new-generation")

    with pytest.raises(AuthFailedError):
        sessions.validate(session.session_id)


def test_file_session_store_prunes_all_expired_rows_on_next_write(tmp_path: Path) -> None:
    credential_path = tmp_path / "auth.json"
    credentials = StrategistCredentialStore(credential_path)
    credentials.initialize_password("secret")
    sessions = FileSessionStore(credentials, ttl=timedelta(hours=24))
    issued_at = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
    expired = sessions.create(now=issued_at)
    active = sessions.create(now=issued_at + timedelta(hours=25))

    document = json.loads(
        credential_path.with_name("auth.sessions.json").read_text(encoding="utf-8"),
    )

    assert set(document["sessions"]) == {active.session_id}
    assert expired.session_id not in document["sessions"]


def test_malformed_session_file_does_not_retain_tokens_in_exception_chain(
    tmp_path: Path,
) -> None:
    credential_path = tmp_path / "auth.json"
    credentials = StrategistCredentialStore(credential_path)
    credentials.initialize_password("secret")
    sessions = FileSessionStore(credentials)
    leaked_token = "session-secret-material"
    atomic_write_private_text(
        credential_path.with_name("auth.sessions.json"),
        f'{{"sessions":{{"{leaked_token}":{{"csrf_token":"{leaked_token}"}}}}}}',
    )

    with pytest.raises(AuthFailedError) as exc_info:
        sessions.validate(leaked_token)

    error = exc_info.value
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    assert leaked_token not in str(error)
    assert leaked_token not in repr(error)
    assert leaked_token not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None
