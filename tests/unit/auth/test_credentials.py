from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.auth.credentials import StrategistCredentialStore
from agentkit.backend.auth.entities import StrategistCredentials
from agentkit.backend.auth.errors import AuthFailedError
from agentkit.backend.boundary.filesystem.private_files import atomic_write_private_text


def test_strategist_password_is_hashed_and_verified(tmp_path: Path) -> None:
    store = StrategistCredentialStore(tmp_path / "auth.json")
    store.initialize_password("correct horse battery staple")

    result = store.verify(
        StrategistCredentials(
            username="admin",
            password="correct horse battery staple",
        ),
    )

    assert result.username == "admin"
    assert "correct horse" not in store.path.read_text(encoding="utf-8")
    assert "argon2" in store.path.read_text(encoding="utf-8")


def test_strategist_password_rejects_wrong_credentials(tmp_path: Path) -> None:
    store = StrategistCredentialStore(tmp_path / "auth.json")
    store.initialize_password("secret")

    with pytest.raises(AuthFailedError):
        store.verify(StrategistCredentials(username="admin", password="wrong"))


def test_malformed_auth_file_does_not_retain_hash_in_exception_chain(tmp_path: Path) -> None:
    leaked_hash = "argon2id-secret-hash-material"
    store = StrategistCredentialStore(tmp_path / "auth.json")
    atomic_write_private_text(
        store.path,
        f'{{"username":"admin","password_hash":"{leaked_hash}"}}',
    )

    with pytest.raises(AuthFailedError) as exc_info:
        store.verify(StrategistCredentials(username="admin", password="submitted-secret"))

    error = exc_info.value
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    assert leaked_hash not in str(error)
    assert leaked_hash not in repr(error)
    assert leaked_hash not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None


def test_invalid_argon2_hash_does_not_survive_auth_exception_channels(tmp_path: Path) -> None:
    leaked_hash = "$argon2id$secret-malformed-phc"
    store = StrategistCredentialStore(tmp_path / "auth.json")
    atomic_write_private_text(
        store.path,
        (
            '{"username":"admin","password_hash":'
            f'"{leaked_hash}","hash_algorithm":"argon2id"}}'
        ),
    )

    with pytest.raises(AuthFailedError) as exc_info:
        store.verify(StrategistCredentials(username="admin", password="submitted-secret"))

    error = exc_info.value
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    assert leaked_hash not in str(error)
    assert leaked_hash not in repr(error)
    assert leaked_hash not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None
