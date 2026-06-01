"""Contract tests for StateBackendSkillBindingRepository (Postgres canonical).

AG3-048, FK-43 §43.4.1 — Roundtrip against real Postgres (the canonical
backend, concept/domain-design/05-telemetrie-und-metriken.md §5). Mirrors
``test_artifact_repository_postgres.py``: skips when neither an explicit
Postgres env nor docker is available.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentkit.skills.binding import (
    SkillBinding,
    SkillBindingMode,
    SkillLifecycleStatus,
)
from agentkit.state_backend.store.skill_binding_repository import (
    StateBackendSkillBindingRepository,
)

pytest_plugins = ("tests.fixtures.postgres_backend",)

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _make_binding(
    *,
    project_key: str,
    skill_name: str = "execute-userstory",
    status: SkillLifecycleStatus = SkillLifecycleStatus.BOUND,
    binding_id: str | None = None,
) -> SkillBinding:
    # binding_id is deterministic from (project_key, skill_name) in production
    # (Skills._binding_id_for); mirror that here so it is globally unique on a
    # persistent Postgres DB shared across tests.
    return SkillBinding(
        binding_id=binding_id or f"{project_key}:{skill_name}",
        project_key=project_key,
        skill_name=skill_name,
        bundle_id="core",
        bundle_version="4.0.0",
        target_path=Path("/repo/.claude/skills") / skill_name,
        binding_mode=SkillBindingMode.SYMLINK,
        status=status,
        pinned_at=_NOW,
    )


@pytest.mark.contract
def test_postgres_skill_binding_roundtrip(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    """save -> load roundtrip against real Postgres (all fields intact)."""
    repo = StateBackendSkillBindingRepository(store_dir=tmp_path)
    binding = _make_binding(project_key="proj-pg-rt")
    repo.save(binding)
    loaded = repo.load("proj-pg-rt", "execute-userstory")
    assert loaded is not None
    assert loaded == binding
    assert loaded.target_path == Path("/repo/.claude/skills/execute-userstory")
    assert loaded.binding_mode is SkillBindingMode.SYMLINK
    assert loaded.status is SkillLifecycleStatus.BOUND
    assert loaded.pinned_at.tzinfo is not None


@pytest.mark.contract
def test_postgres_skill_binding_upsert(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    """Re-save on (project_key, skill_name) updates in place (BOUND->VERIFIED)."""
    repo = StateBackendSkillBindingRepository(store_dir=tmp_path)
    pk = "proj-pg-upsert"
    repo.save(_make_binding(project_key=pk, status=SkillLifecycleStatus.BOUND))
    repo.save(_make_binding(project_key=pk, status=SkillLifecycleStatus.VERIFIED))
    loaded = repo.load(pk, "execute-userstory")
    assert loaded is not None
    assert loaded.status is SkillLifecycleStatus.VERIFIED
    assert len(repo.list_for_project(pk)) == 1


@pytest.mark.contract
def test_postgres_skill_binding_list_sorted(
    tmp_path: Path,
    postgres_backend_env: object,
) -> None:
    """list_for_project returns deterministically sorted, project-isolated rows."""
    repo = StateBackendSkillBindingRepository(store_dir=tmp_path)
    pk = "proj-pg-list"
    for i, name in enumerate(["zzz", "aaa", "mmm"]):
        repo.save(_make_binding(project_key=pk, skill_name=name, binding_id=f"pg-{i}"))
    other = _make_binding(project_key="proj-pg-other", binding_id="pg-other")
    repo.save(other)
    names = [b.skill_name for b in repo.list_for_project(pk)]
    assert names == ["aaa", "mmm", "zzz"]
    assert len(repo.list_for_project("proj-pg-other")) == 1
