"""SQLite CRUD tests for StateBackendProjectRegistrationRepository (AG3-039).

Unit path is SQLite-only (tests/unit/conftest.py forces sqlite + drops the
Postgres DSN); the real Postgres path is exercised by the integration test.
Covers all five Protocol methods plus the upgrade/verify mutations and the
fail-closed duplicate-key behaviour.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentkit.installer.registration import ProjectRegistration, RuntimeProfile
from agentkit.installer.repository import ProjectRegistrationRepository
from agentkit.state_backend.store.project_registration_repository import (
    StateBackendProjectRegistrationRepository,
)

_REGISTERED_AT = datetime(2026, 6, 4, 10, 0, tzinfo=UTC)


def _make(
    project_key: str, *, digest: str, profile: RuntimeProfile
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


def test_repository_satisfies_protocol(tmp_path: Path) -> None:
    repo = StateBackendProjectRegistrationRepository(tmp_path)
    assert isinstance(repo, ProjectRegistrationRepository)


def test_get_missing_returns_none(tmp_path: Path) -> None:
    repo = StateBackendProjectRegistrationRepository(tmp_path)
    assert repo.get("absent") is None


def test_save_then_get_roundtrip(tmp_path: Path) -> None:
    repo = StateBackendProjectRegistrationRepository(tmp_path)
    reg = _make("demo", digest="a" * 64, profile=RuntimeProfile.ARE)
    repo.save(reg)
    loaded = repo.get("demo")
    assert loaded == reg
    assert loaded is not None
    assert loaded.runtime_profile is RuntimeProfile.ARE
    assert loaded.last_verified_at is None
    assert loaded.last_upgraded_at is None


def test_list_all_sorted(tmp_path: Path) -> None:
    repo = StateBackendProjectRegistrationRepository(tmp_path)
    repo.save(_make("zeta", digest="1" * 64, profile=RuntimeProfile.CORE))
    repo.save(_make("alpha", digest="2" * 64, profile=RuntimeProfile.CORE))
    keys = [r.project_key for r in repo.list_all()]
    assert keys == ["alpha", "zeta"]


def test_update_verified_sets_timestamp(tmp_path: Path) -> None:
    repo = StateBackendProjectRegistrationRepository(tmp_path)
    repo.save(_make("demo", digest="a" * 64, profile=RuntimeProfile.CORE))
    verified_at = datetime(2026, 6, 5, tzinfo=UTC)
    repo.update_verified("demo", verified_at)
    loaded = repo.get("demo")
    assert loaded is not None
    assert loaded.last_verified_at == verified_at
    assert loaded.last_upgraded_at is None


def test_update_upgraded_changes_digest_and_timestamp(tmp_path: Path) -> None:
    repo = StateBackendProjectRegistrationRepository(tmp_path)
    repo.save(_make("demo", digest="a" * 64, profile=RuntimeProfile.CORE))
    upgraded_at = datetime(2026, 6, 6, tzinfo=UTC)
    repo.update_upgraded("demo", upgraded_at, "b" * 64)
    loaded = repo.get("demo")
    assert loaded is not None
    assert loaded.config_digest == "b" * 64
    assert loaded.last_upgraded_at == upgraded_at


def test_duplicate_save_fails_closed(tmp_path: Path) -> None:
    repo = StateBackendProjectRegistrationRepository(tmp_path)
    repo.save(_make("demo", digest="a" * 64, profile=RuntimeProfile.CORE))
    # Re-inserting the same primary key must fail (no silent overwrite — the
    # idempotency/upgrade decision lives in the installer CP 7, not here).
    with pytest.raises(sqlite3.IntegrityError):
        repo.save(_make("demo", digest="c" * 64, profile=RuntimeProfile.CORE))


def test_update_verified_missing_key_fails_closed(tmp_path: Path) -> None:
    """W6: update_verified on an unknown project_key must raise, not no-op."""
    repo = StateBackendProjectRegistrationRepository(tmp_path)
    with pytest.raises(LookupError):
        repo.update_verified("absent", datetime(2026, 6, 5, tzinfo=UTC))


def test_update_upgraded_missing_key_fails_closed(tmp_path: Path) -> None:
    """W6: update_upgraded on an unknown project_key must raise, not no-op."""
    repo = StateBackendProjectRegistrationRepository(tmp_path)
    with pytest.raises(LookupError):
        repo.update_upgraded("absent", datetime(2026, 6, 6, tzinfo=UTC), "b" * 64)


def test_unique_project_root_fails_closed(tmp_path: Path) -> None:
    repo = StateBackendProjectRegistrationRepository(tmp_path)
    repo.save(_make("demo", digest="a" * 64, profile=RuntimeProfile.CORE))
    clash = ProjectRegistration(
        project_key="other",
        project_root=Path("/srv/demo"),  # same root as "demo"
        github_owner="acme",
        github_repo="other",
        runtime_profile=RuntimeProfile.CORE,
        config_version="1",
        config_digest="d" * 64,
        registered_at=_REGISTERED_AT,
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.save(clash)
