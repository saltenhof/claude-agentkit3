from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.auth.credentials import StrategistCredentialStore
from agentkit.backend.auth.entities import StrategistCredentials
from agentkit.backend.auth.errors import AuthFailedError


def test_strategist_password_is_hashed_and_verified(tmp_path: Path) -> None:
    store = StrategistCredentialStore(tmp_path / "auth.json")
    store.set_password("correct horse battery staple", username="strategist")

    result = store.verify(
        StrategistCredentials(
            username="strategist",
            password="correct horse battery staple",
        ),
    )

    assert result.username == "strategist"
    assert "correct horse" not in store.path.read_text(encoding="utf-8")
    assert "argon2" in store.path.read_text(encoding="utf-8")


def test_strategist_password_rejects_wrong_credentials(tmp_path: Path) -> None:
    store = StrategistCredentialStore(tmp_path / "auth.json")
    store.set_password("secret", username="strategist")

    with pytest.raises(AuthFailedError):
        store.verify(StrategistCredentials(username="strategist", password="wrong"))
