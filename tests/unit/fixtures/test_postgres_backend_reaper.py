"""Unit tests for the Postgres fixture container reaper safety predicate."""

from __future__ import annotations

import pytest
from tests.fixtures import postgres_backend

from agentkit.backend.state_backend.config import STATE_BACKEND_ENV, STATE_DATABASE_URL_ENV


def test_explicit_postgres_env_uses_import_time_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(postgres_backend, "_EXPLICIT_BACKEND_AT_IMPORT", "postgres")
    monkeypatch.setattr(
        postgres_backend,
        "_EXPLICIT_URL_AT_IMPORT",
        "postgresql://agentkit:test@localhost:15432/agentkit_test",
    )
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.delenv(STATE_DATABASE_URL_ENV, raising=False)

    assert postgres_backend._is_explicit_postgres_env() is True


def test_non_postgres_import_snapshot_ignores_later_live_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(postgres_backend, "_EXPLICIT_BACKEND_AT_IMPORT", "sqlite")
    monkeypatch.setattr(postgres_backend, "_EXPLICIT_URL_AT_IMPORT", None)
    monkeypatch.setenv(STATE_BACKEND_ENV, "postgres")
    monkeypatch.setenv(
        STATE_DATABASE_URL_ENV,
        "postgresql://agentkit:test@localhost:15432/agentkit_test",
    )

    assert postgres_backend._is_explicit_postgres_env() is False


def test_explicit_postgres_url_rejects_reserved_production_port() -> None:
    with pytest.raises(RuntimeError, match="reserved production standard port 5432"):
        postgres_backend._ensure_explicit_postgres_url_uses_test_port(
            "postgresql://agentkit:test@localhost:5432/agentkit_test",
        )


def test_explicit_postgres_url_accepts_non_standard_test_port() -> None:
    postgres_backend._ensure_explicit_postgres_url_uses_test_port(
        "postgresql://agentkit:test@localhost:15432/agentkit_test",
    )


def test_find_free_port_rerolls_reserved_production_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ports = iter([5432, 15432])

    monkeypatch.setattr(
        postgres_backend,
        "_find_socket_port",
        lambda: next(ports),
    )

    assert postgres_backend._find_free_port() == 15432


def test_non_reserved_test_postgres_port_is_accepted() -> None:
    assert postgres_backend._ensure_non_reserved_test_postgres_port(15432) == 15432


@pytest.mark.parametrize(
    ("name", "label_value", "age_seconds", "expected"),
    [
        ("ak3-postgres-012345abcdef", None, 7200.1, True),
        ("custom-container-name", "1", 7200.1, True),
        ("ak3-postgres-012345abcdeg", None, 7200.1, False),
        ("agentkit-postgres-ci", None, 7200.1, False),
        ("agentkit-postgres-ci-55432", None, 7200.1, False),
        ("seu-sonar-db", None, 7200.1, False),
        ("arbitrary-container", None, 7200.1, False),
        ("ak3-postgres-012345abcdef", "0", 7200.1, True),
        ("ak3-postgres-012345abcdef", None, 7200.0, False),
        ("custom-container-name", "1", 7200.0, False),
    ],
    ids=[
        "legacy_exact_name_is_reapable_after_ttl",
        "label_owned_name_is_reapable_after_ttl",
        "legacy_name_requires_12_hex_chars",
        "agentkit_postgres_ci_is_not_reapable",
        "agentkit_postgres_ci_port_variant_is_not_reapable",
        "sonar_db_is_not_reapable",
        "arbitrary_unlabelled_name_is_not_reapable",
        "legacy_exact_name_does_not_need_label",
        "legacy_exact_name_at_ttl_boundary_is_not_reapable",
        "label_owned_name_at_ttl_boundary_is_not_reapable",
    ],
)
def test_is_reapable_test_container_requires_fixture_marker_and_age(
    name: str,
    label_value: str | None,
    age_seconds: float,
    expected: bool,
) -> None:
    assert (
        postgres_backend._is_reapable_test_container(
            name,
            label_value,
            age_seconds,
            ttl_seconds=7200.0,
        )
        is expected
    )
