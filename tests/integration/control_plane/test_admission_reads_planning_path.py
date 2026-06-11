"""Admission/readiness reads dependency edges from the planning path (AC5, FIX 3).

FK-70 §70.10.2 SINGLE SOURCE OF TRUTH: the run-admission readiness reader
(``build_execution_planning_admission_reader``) must read dependency edges from
the SAME BC-9 planning projection path that planning writes go to
(``planning_dependency_edge``), not the legacy direct ``story_dependencies``
table. Before FIX 3 the admission reader constructed the legacy
``StateBackendStoryDependencyRepository`` -- so a story READY-blocking edge
written via the planning path was invisible to admission (read/write split).

This test writes a real B->A edge through the planning write path and proves the
admission reader honours it: B is NOT admitted (blocked by the open dependency)
while A is admitted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.bootstrap.composition_root import (
    build_planning_story_dependency_repository,
)
from agentkit.control_plane.dispatch import build_execution_planning_admission_reader
from agentkit.core_types import StoryDependencyKind
from agentkit.execution_planning.entities import StoryDependency
from agentkit.project_management.entities import ProjectConfiguration
from agentkit.project_management.lifecycle import create_project
from agentkit.state_backend.store import facade
from agentkit.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.state_backend.store.story_repository import (
    StateBackendIdempotencyKeyRepository,
    StateBackendStoryRepository,
)
from agentkit.story_context_manager.service import StoryService
from agentkit.story_context_manager.story_model import CreateStoryInput

if TYPE_CHECKING:
    from pathlib import Path

_PROJECT = "tenant-a"


@pytest.fixture(autouse=True)
def _sqlite_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    facade.reset_backend_cache_for_tests()


def _story_service(tmp_path: Path) -> StoryService:
    return StoryService(
        story_repository=StateBackendStoryRepository(tmp_path),
        project_repository=StateBackendProjectRepository(tmp_path),
        idempotency_repository=StateBackendIdempotencyKeyRepository(tmp_path),
        event_emitter=lambda *_: None,
    )


def _seed_project(tmp_path: Path) -> None:
    config = ProjectConfiguration(
        repo_url="",
        default_branch="main",
        default_worker_count=2,
        repositories=["repo-a"],
    )
    StateBackendProjectRepository(tmp_path).save(
        create_project(_PROJECT, "Tenant A", "AG3", config, repositories=["repo-a"]),
    )


def test_admission_reader_sees_planning_path_edge(tmp_path: Path) -> None:
    """A planning-path edge blocks the dependent story in admission readiness."""
    _seed_project(tmp_path)
    service = _story_service(tmp_path)
    story_a = service.create_story(
        CreateStoryInput(
            project_key=_PROJECT, title="Predecessor A",
            type="implementation", repos=["repo-a"],
        ),
        op_id="op-a",
    )
    story_b = service.create_story(
        CreateStoryInput(
            project_key=_PROJECT, title="Dependent B",
            type="implementation", repos=["repo-a"],
        ),
        op_id="op-b",
    )
    service.approve_story(story_a.story_display_id, op_id="op-approve-a")
    service.approve_story(story_b.story_display_id, op_id="op-approve-b")

    # Write a real B -> A edge through the PLANNING projection write path.
    dep_repo = build_planning_story_dependency_repository(tmp_path)
    dep_repo.add(
        StoryDependency(
            story_id=story_b.story_display_id,
            depends_on_story_id=story_a.story_display_id,
            kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            created_at=datetime.now(UTC),
        ),
        project_key=_PROJECT,
    )

    reader = build_execution_planning_admission_reader(tmp_path)

    # A has no open dependency -> admitted; B is blocked by the planning-path
    # edge -> NOT admitted. This only holds if admission reads the SAME table.
    assert reader.is_ready_and_admitted(_PROJECT, story_a.story_display_id) is True
    assert reader.is_ready_and_admitted(_PROJECT, story_b.story_display_id) is False
