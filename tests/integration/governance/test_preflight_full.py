"""Integration test — full ten-check setup preflight run (FK-22 §22.3.1).

DB-backed (SQLite) end-to-end run of ``run_preflight`` against a real
``StoryService`` + ``ModeLockRepository`` for an approved implementation story.
Covers the all-green happy path and a multi-failure path that still runs all
ten checks (FK-22 §22.3.2, AK1).  No mocks: real repositories against a
``tmp_path``-scoped SQLite DB; filesystem residue via ``tmp_path`` (story.md §8).
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.composition_root import build_phase_state_residue_probe
from agentkit.backend.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightStatus,
    run_preflight,
)
from agentkit.backend.project_management.entities import ProjectConfiguration
from agentkit.backend.project_management.lifecycle import create_project
from agentkit.backend.state_backend.store import facade
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    InMemoryInflightIdempotencyGuard,
)
from agentkit.backend.state_backend.store.mode_lock_repository import ModeLockRepository
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.backend.state_backend.store.story_dependency_repository import (
    StateBackendStoryDependencyRepository,
)
from agentkit.backend.state_backend.store.story_repository import (
    StateBackendStoryRepository,
)
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import CreateStoryInput

if TYPE_CHECKING:
    from pathlib import Path

_PROJECT = "tenant-a"
_TS = "2026-06-02T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    facade.reset_backend_cache_for_tests()


def _story_service(tmp_path: Path) -> StoryService:
    return StoryService(
        story_repository=StateBackendStoryRepository(tmp_path),
        project_repository=StateBackendProjectRepository(tmp_path),
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        dependency_repository=StateBackendStoryDependencyRepository(tmp_path),
        event_emitter=lambda *_: None,
    )


def _seed_project(tmp_path: Path) -> None:
    repo = StateBackendProjectRepository(tmp_path)
    config = ProjectConfiguration(
        repo_url="",
        default_branch="main",
        default_worker_count=2,
        repositories=["repo-a"],
    )
    repo.save(
        create_project(_PROJECT, "Tenant A", "AG3", config, repositories=["repo-a"]),
    )


def _git(root: Path, *args: str) -> None:
    """Run a git command in ``root`` (real repo for the Check-7 branch probe)."""
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> None:
    """Initialise a real git repo so Check 7's ``git show-ref`` probe can run.

    Finding B: Check 7 reads the real repo (fail-closed on a non-repo); the
    happy path therefore needs an actual repository with no ``story/*`` branch.
    """
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "seed.txt").write_text("x", encoding="utf-8")
    _git(tmp_path, "add", "seed.txt")
    _git(tmp_path, "commit", "-q", "-m", "seed")


def _approved_story(service: StoryService) -> str:
    story = service.create_story(
        CreateStoryInput(
            project_key=_PROJECT,
            title="Preflight target",
            type="implementation",
            repos=["repo-a"],
        ),
        op_id="op-create",
    )
    service.approve_story(story.story_display_id, op_id="op-approve")
    return story.story_display_id


def test_all_ten_checks_pass_for_clean_approved_story(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _seed_project(tmp_path)
    service = _story_service(tmp_path)
    story_id = _approved_story(service)

    result = run_preflight(
        story_id,
        service,
        project_key=_PROJECT,
        project_root=tmp_path,
        active_runtime_residue=build_phase_state_residue_probe(tmp_path),
    )

    assert len(result.checks) == 10
    assert result.overall is PreflightStatus.PASS
    assert result.failed_check_ids == ()
    assert {c.check_id for c in result.checks} == set(PreflightCheckId)


def test_multiple_failures_still_run_all_ten_checks(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _seed_project(tmp_path)
    service = _story_service(tmp_path)
    story_id = _approved_story(service)

    # Residual execution artifacts (Check 5 fail).
    residue = tmp_path / "_temp" / "stories" / story_id
    residue.mkdir(parents=True)
    (residue / "leftover.json").write_text("{}", encoding="utf-8")

    # Competing FAST mode-lock held by another standard run (Check 10 fail).
    ModeLockRepository(tmp_path).set_lock(
        _PROJECT, active_mode="fast", holder_count=1, updated_at=_TS
    )
    mode_lock = ModeLockRepository(tmp_path).read_lock(_PROJECT)

    result = run_preflight(
        story_id,
        service,
        project_key=_PROJECT,
        project_root=tmp_path,
        mode_lock=mode_lock,
        active_runtime_residue=build_phase_state_residue_probe(tmp_path),
    )

    assert len(result.checks) == 10  # all run despite multiple failures
    assert result.overall is PreflightStatus.FAIL
    assert PreflightCheckId.NO_EXECUTION_ARTIFACTS in result.failed_check_ids
    assert PreflightCheckId.NO_COMPETING_STORY_MODE_ACTIVE in result.failed_check_ids
    # Every failure carries a cleanup hint (FK-22 §22.3.4, AK3).
    for check in result.checks:
        if check.status is PreflightStatus.FAIL:
            assert check.cleanup_hint is not None
    # Story existence / status remained green.
    assert PreflightCheckId.STORY_EXISTS not in result.failed_check_ids
    assert PreflightCheckId.STATUS_APPROVED not in result.failed_check_ids
