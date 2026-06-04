"""Contract tests for StateBackendProjectRegistrationRepository (Postgres canonical).

AG3-039 (FK-50 §50.3 CP 7) — CRUD roundtrip against real Postgres, the canonical
backend (concept/domain-design/05-telemetrie-und-metriken.md §5). Mirrors
``test_skill_binding_repository_postgres.py``: the contract conftest auto-binds
``postgres_isolated_schema`` to every ``/contract/state_backend/`` item.

Parametrised counterpart to the SQLite-only unit test
(``tests/unit/state_backend/store/test_project_registration_repository.py``).
Covers all five Protocol methods (``save``/``get``/``list_all``/
``update_verified``/``update_upgraded``), the ``TIMESTAMPTZ`` datetime roundtrip
(E1), the ``UNIQUE(project_root)`` and ``CHECK(runtime_profile)`` constraints,
and the fail-closed lifecycle mutations on a missing key (W6).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
import pytest
from psycopg import errors as pg_errors
from psycopg import sql

from agentkit.installer.registration import ProjectRegistration, RuntimeProfile
from agentkit.state_backend.config import resolve_schema_name
from agentkit.state_backend.store.project_registration_repository import (
    StateBackendProjectRegistrationRepository,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytest_plugins = ("tests.fixtures.postgres_backend",)

_REGISTERED_AT = datetime(2026, 6, 4, 10, 0, tzinfo=UTC)


def _make(
    project_key: str, *, digest: str, profile: RuntimeProfile = RuntimeProfile.CORE
) -> ProjectRegistration:
    return ProjectRegistration(
        project_key=project_key,
        project_root=Path(f"/srv/{project_key}"),
        github_owner="acme",
        github_repo=project_key,
        runtime_profile=profile,
        config_version="1",
        config_digest=digest,
        registered_at=_REGISTERED_AT,
    )


@pytest.fixture()
def _pg_conn(postgres_backend_env: str) -> Iterator[psycopg.Connection[object]]:
    """Raw connection on the isolated test schema (for direct-DDL assertions)."""
    schema = resolve_schema_name()
    conn = psycopg.connect(os.environ["AGENTKIT_STATE_DATABASE_URL"], autocommit=True)
    conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
    try:
        yield conn
    finally:
        conn.close()


@pytest.mark.contract
def test_postgres_save_get_roundtrip_timestamptz(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    """save -> get against real Postgres; TIMESTAMPTZ roundtrips tz-aware (E1)."""
    repo = StateBackendProjectRegistrationRepository(store_dir=tmp_path)
    reg = _make("pg-rt", digest="a" * 64, profile=RuntimeProfile.ARE)
    repo.save(reg)
    loaded = repo.get("pg-rt")
    assert loaded is not None
    assert loaded == reg
    assert loaded.runtime_profile is RuntimeProfile.ARE
    assert loaded.registered_at == _REGISTERED_AT
    assert loaded.registered_at.tzinfo is not None
    assert loaded.last_verified_at is None
    assert loaded.last_upgraded_at is None


@pytest.mark.contract
def test_postgres_get_missing_returns_none(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    repo = StateBackendProjectRegistrationRepository(store_dir=tmp_path)
    assert repo.get("pg-absent") is None


@pytest.mark.contract
def test_postgres_list_all_sorted(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    repo = StateBackendProjectRegistrationRepository(store_dir=tmp_path)
    repo.save(_make("pg-zeta", digest="1" * 64))
    repo.save(_make("pg-alpha", digest="2" * 64))
    keys = [r.project_key for r in repo.list_all()]
    assert keys == ["pg-alpha", "pg-zeta"]


@pytest.mark.contract
def test_postgres_update_verified(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    repo = StateBackendProjectRegistrationRepository(store_dir=tmp_path)
    repo.save(_make("pg-verify", digest="a" * 64))
    verified_at = datetime(2026, 6, 5, 9, 30, tzinfo=UTC)
    repo.update_verified("pg-verify", verified_at)
    loaded = repo.get("pg-verify")
    assert loaded is not None
    assert loaded.last_verified_at == verified_at
    assert loaded.last_upgraded_at is None


@pytest.mark.contract
def test_postgres_update_upgraded(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    repo = StateBackendProjectRegistrationRepository(store_dir=tmp_path)
    repo.save(_make("pg-upgrade", digest="a" * 64))
    upgraded_at = datetime(2026, 6, 6, 8, 15, tzinfo=UTC)
    repo.update_upgraded("pg-upgrade", upgraded_at, "b" * 64)
    loaded = repo.get("pg-upgrade")
    assert loaded is not None
    assert loaded.config_digest == "b" * 64
    assert loaded.last_upgraded_at == upgraded_at


@pytest.mark.contract
def test_postgres_update_verified_missing_key_fails_closed(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    """W6: 0-row update on Postgres must raise, not be a silent success."""
    repo = StateBackendProjectRegistrationRepository(store_dir=tmp_path)
    with pytest.raises(LookupError):
        repo.update_verified("pg-absent", datetime(2026, 6, 5, tzinfo=UTC))


@pytest.mark.contract
def test_postgres_update_upgraded_missing_key_fails_closed(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    repo = StateBackendProjectRegistrationRepository(store_dir=tmp_path)
    with pytest.raises(LookupError):
        repo.update_upgraded("pg-absent", datetime(2026, 6, 6, tzinfo=UTC), "b" * 64)


@pytest.mark.contract
def test_postgres_unique_project_root_fails_closed(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    """UNIQUE(project_root): two keys cannot share one filesystem root."""
    repo = StateBackendProjectRegistrationRepository(store_dir=tmp_path)
    repo.save(_make("pg-root-a", digest="a" * 64))
    clash = ProjectRegistration(
        project_key="pg-root-b",
        project_root=Path("/srv/pg-root-a"),  # same root
        github_owner="acme",
        github_repo="pg-root-b",
        runtime_profile=RuntimeProfile.CORE,
        config_version="1",
        config_digest="d" * 64,
        registered_at=_REGISTERED_AT,
    )
    with pytest.raises(pg_errors.UniqueViolation):
        repo.save(clash)


@pytest.mark.contract
def test_postgres_duplicate_primary_key_fails_closed(
    tmp_path: Path, postgres_backend_env: str
) -> None:
    repo = StateBackendProjectRegistrationRepository(store_dir=tmp_path)
    repo.save(_make("pg-dup", digest="a" * 64))
    with pytest.raises(pg_errors.UniqueViolation):
        repo.save(_make("pg-dup", digest="c" * 64))


@pytest.mark.contract
def test_postgres_runtime_profile_check_constraint(
    _pg_conn: psycopg.Connection[object],
) -> None:
    """CHECK(runtime_profile IN ('core','are')): the DB rejects other values.

    Driven via raw SQL because the ``RuntimeProfile`` enum already prevents an
    invalid value from ever reaching the row through the typed repository — this
    proves the constraint lives in the DDL, not only in the Pydantic model.
    """
    with pytest.raises(pg_errors.CheckViolation):
        _pg_conn.execute(
            "INSERT INTO project_registry (project_key, project_root, github_owner, "
            "github_repo, runtime_profile, config_version, config_digest, "
            "registered_at) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                "pg-bad-profile",
                "/srv/pg-bad-profile",
                "acme",
                "pg-bad-profile",
                "hybrid",
                "1",
                "a" * 64,
                _REGISTERED_AT,
            ),
        )
