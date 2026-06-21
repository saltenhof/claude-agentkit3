"""SQLite roundtrip tests for StateBackendSkillBindingRepository (AG3-048).

Unit-Pfad ist SQLite-only (tests/unit/conftest.py erzwingt sqlite + loescht die
Postgres-DSN). Der kanonische Postgres-Roundtrip liegt im Contract-Test
``tests/contract/state_backend/test_skill_binding_repository_postgres.py``
(analog ``test_artifact_repository_postgres.py``).

Verifiziert (SQLite test-parallel, ``AGENTKIT_ALLOW_SQLITE=1``):

- save -> load roundtrip with all fields intact (target_path Path<->TEXT,
  enums by value, tz-aware pinned_at)
- save upsert on (project_key, skill_name): re-save replaces the row in place
  (the BOUND->VERIFIED lifecycle transition from Skills.bind_skill)
- list_for_project sorted by skill_name + project isolation
- Protocol satisfaction (StateBackendSkillBindingRepository IS-A
  SkillBindingRepository)
- fail-closed DB CHECKs (status, binding_mode)
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.skills.binding import (
    SkillBinding,
    SkillBindingMode,
    SkillLifecycleStatus,
)
from agentkit.backend.skills.repository import SkillBindingRepository
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.store.skill_binding_repository import (
    StateBackendSkillBindingRepository,
)

if TYPE_CHECKING:
    from collections.abc import Generator

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _make_binding(
    *,
    project_key: str = "proj-a",
    skill_name: str = "execute-userstory",
    status: SkillLifecycleStatus = SkillLifecycleStatus.BOUND,
    binding_id: str = "bind-1",
    bundle_version: str = "4.0.0",
) -> SkillBinding:
    return SkillBinding(
        binding_id=binding_id,
        project_key=project_key,
        skill_name=skill_name,
        bundle_id="core",
        bundle_version=bundle_version,
        target_path=Path("/repo/.claude/skills") / skill_name,
        binding_mode=SkillBindingMode.SYMLINK,
        status=status,
        pinned_at=_NOW,
    )


# ---------------------------------------------------------------------------
# SQLite env
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    from agentkit.backend.state_backend.store import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


def test_satisfies_protocol(tmp_path: Path) -> None:
    repo = StateBackendSkillBindingRepository(tmp_path)
    assert isinstance(repo, SkillBindingRepository)


# ---------------------------------------------------------------------------
# SQLite roundtrip
# ---------------------------------------------------------------------------


class TestSqliteRoundtrip:
    def test_save_and_load(self, sqlite_env: None, tmp_path: Path) -> None:
        repo = StateBackendSkillBindingRepository(tmp_path)
        binding = _make_binding()
        repo.save(binding)
        loaded = repo.load("proj-a", "execute-userstory")
        assert loaded is not None
        assert loaded == binding
        assert loaded.target_path == Path("/repo/.claude/skills/execute-userstory")
        assert loaded.binding_mode is SkillBindingMode.SYMLINK
        assert loaded.status is SkillLifecycleStatus.BOUND
        assert loaded.pinned_at.tzinfo is not None

    def test_aware_non_utc_offset_survives_roundtrip(
        self, sqlite_env: None, tmp_path: Path
    ) -> None:
        """A non-UTC aware offset (+02:00) survives the roundtrip byte-identical.

        Regression for the silent ``.astimezone(UTC)`` coercion (AG3-048
        Codex review ERROR 3): ``2026-06-01T14:00:00+02:00`` must NOT come
        back as ``2026-06-01T12:00:00+00:00``. Both the wall-clock value AND
        the tzinfo (offset) are preserved exactly, mirroring the FK-18
        ``attempt_row_to_record`` pattern.
        """
        plus_two = timezone(timedelta(hours=2))
        pinned = datetime(2026, 6, 1, 14, 0, 0, tzinfo=plus_two)
        repo = StateBackendSkillBindingRepository(tmp_path)
        binding = SkillBinding(
            binding_id="tz-1",
            project_key="proj-tz",
            skill_name="execute-userstory",
            bundle_id="core",
            bundle_version="4.0.0",
            target_path=Path("/repo/.claude/skills/execute-userstory"),
            binding_mode=SkillBindingMode.SYMLINK,
            status=SkillLifecycleStatus.BOUND,
            pinned_at=pinned,
        )
        repo.save(binding)
        loaded = repo.load("proj-tz", "execute-userstory")
        assert loaded is not None
        # Same instant AND same serialized shape (offset + tzinfo), not UTC.
        assert loaded.pinned_at == pinned
        assert loaded.pinned_at.isoformat() == "2026-06-01T14:00:00+02:00"
        assert loaded.pinned_at.utcoffset() == timedelta(hours=2)

    def test_load_missing_returns_none(self, sqlite_env: None, tmp_path: Path) -> None:
        repo = StateBackendSkillBindingRepository(tmp_path)
        assert repo.load("no-proj", "no-skill") is None

    def test_upsert_on_project_skill(self, sqlite_env: None, tmp_path: Path) -> None:
        repo = StateBackendSkillBindingRepository(tmp_path)
        repo.save(_make_binding(status=SkillLifecycleStatus.BOUND))
        # Re-save with the SAME (project_key, skill_name) -> in-place update
        # (the BOUND->VERIFIED transition Skills.bind_skill performs).
        repo.save(_make_binding(status=SkillLifecycleStatus.VERIFIED))
        loaded = repo.load("proj-a", "execute-userstory")
        assert loaded is not None
        assert loaded.status is SkillLifecycleStatus.VERIFIED
        # Exactly one row for the natural key.
        assert len(repo.list_for_project("proj-a")) == 1

    def test_list_for_project_sorted(self, sqlite_env: None, tmp_path: Path) -> None:
        repo = StateBackendSkillBindingRepository(tmp_path)
        for i, name in enumerate(["zzz", "aaa", "mmm"]):
            repo.save(_make_binding(skill_name=name, binding_id=f"b{i}"))
        names = [b.skill_name for b in repo.list_for_project("proj-a")]
        assert names == ["aaa", "mmm", "zzz"]

    def test_list_for_project_isolates(self, sqlite_env: None, tmp_path: Path) -> None:
        repo = StateBackendSkillBindingRepository(tmp_path)
        repo.save(_make_binding(project_key="proj-a", binding_id="a1"))
        repo.save(_make_binding(project_key="proj-b", binding_id="b1"))
        assert len(repo.list_for_project("proj-a")) == 1
        assert len(repo.list_for_project("proj-b")) == 1
        assert repo.list_for_project("proj-a")[0].project_key == "proj-a"

    def test_all_six_lifecycle_states_persist(
        self, sqlite_env: None, tmp_path: Path
    ) -> None:
        repo = StateBackendSkillBindingRepository(tmp_path)
        for i, status in enumerate(SkillLifecycleStatus):
            repo.save(
                _make_binding(
                    skill_name=f"skill-{status.value.lower()}",
                    binding_id=f"id-{i}",
                    status=status,
                )
            )
        loaded = {b.skill_name: b.status for b in repo.list_for_project("proj-a")}
        assert set(loaded.values()) == set(SkillLifecycleStatus)

    def test_fail_closed_on_corrupt_status(
        self, sqlite_env: None, tmp_path: Path
    ) -> None:
        """A row written with an unknown status is rejected by the DB CHECK and,
        if forced past it, by the mapper (NO ERROR BYPASSING).
        """
        from agentkit.backend.state_backend.store.skill_binding_repository import (
            _sqlite_connect,
        )

        repo = StateBackendSkillBindingRepository(tmp_path)
        repo.save(_make_binding())
        with _sqlite_connect(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO skill_bindings (binding_id, project_key, skill_name, "
                "bundle_id, bundle_version, target_path, binding_mode, status, "
                "pinned_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "bad-1",
                    "proj-a",
                    "bad-skill",
                    "core",
                    "1.0",
                    "/x",
                    "SYMLINK",
                    "NOT_A_STATUS",
                    _NOW.isoformat(),
                ),
            )
            conn.commit()

    def test_db_check_rejects_non_symlink_mode(
        self, sqlite_env: None, tmp_path: Path
    ) -> None:
        from agentkit.backend.state_backend.store.skill_binding_repository import (
            _sqlite_connect,
        )

        with _sqlite_connect(tmp_path) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO skill_bindings (binding_id, project_key, skill_name, "
                "bundle_id, bundle_version, target_path, binding_mode, status, "
                "pinned_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "bad-2",
                    "proj-a",
                    "x",
                    "core",
                    "1.0",
                    "/x",
                    "COPY",  # not SYMLINK
                    "BOUND",
                    _NOW.isoformat(),
                ),
            )
            conn.commit()
