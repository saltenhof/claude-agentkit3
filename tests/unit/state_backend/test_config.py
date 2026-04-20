from __future__ import annotations

import pytest

from agentkit.state_backend.config import (
    ALLOW_SQLITE_ENV,
    STATE_BACKEND_ENV,
    STATE_DATABASE_URL_ENV,
    StateBackendKind,
    load_state_backend_config,
)


def test_defaults_to_postgres_when_backend_env_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(STATE_BACKEND_ENV, raising=False)
    monkeypatch.delenv(STATE_DATABASE_URL_ENV, raising=False)
    monkeypatch.delenv(ALLOW_SQLITE_ENV, raising=False)

    config = load_state_backend_config()

    assert config.backend is StateBackendKind.POSTGRES
    assert config.database_url is None


def test_sqlite_requires_explicit_allow_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.delenv(ALLOW_SQLITE_ENV, raising=False)

    with pytest.raises(RuntimeError, match="SQLite backend is disabled"):
        load_state_backend_config()


def test_sqlite_is_allowed_for_explicit_unit_test_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")

    config = load_state_backend_config()

    assert config.backend is StateBackendKind.SQLITE


def test_postgres_accepts_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STATE_BACKEND_ENV, "postgres")
    monkeypatch.setenv(
        STATE_DATABASE_URL_ENV,
        "postgresql://agentkit:agentkit@127.0.0.1:5432/agentkit_test",
    )

    config = load_state_backend_config()

    assert config.backend is StateBackendKind.POSTGRES
    assert config.database_url == (
        "postgresql://agentkit:agentkit@127.0.0.1:5432/agentkit_test"
    )


def test_unsupported_backend_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STATE_BACKEND_ENV, "mysql")

    with pytest.raises(RuntimeError, match="Unsupported AGENTKIT_STATE_BACKEND"):
        load_state_backend_config()
