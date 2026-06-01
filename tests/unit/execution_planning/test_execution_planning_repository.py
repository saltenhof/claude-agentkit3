from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.execution_planning.entities import (
    ParallelizationConfig,
    StoryDependencyKind,
)
from agentkit.execution_planning.errors import StoryDependencyConflictError
from agentkit.execution_planning.lifecycle import add_dependency
from agentkit.project_management.entities import ProjectConfiguration
from agentkit.project_management.lifecycle import create_project
from agentkit.state_backend.store import facade
from agentkit.state_backend.store.parallelization_config_repository import (
    StateBackendParallelizationConfigRepository,
)
from agentkit.state_backend.store.planning_story_repository import (
    StateBackendPlanningStoryRepository,
)
from agentkit.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.state_backend.store.story_context_repository import (
    StateBackendStoryContextRepository,
)
from agentkit.state_backend.store.story_dependency_repository import (
    StateBackendStoryDependencyRepository,
)
from agentkit.state_backend.store.story_repository import (
    StateBackendIdempotencyKeyRepository,
    StateBackendStoryRepository,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.service import StoryService
from agentkit.story_context_manager.story_model import (
    CreateStoryInput,
    WireStoryType,
)
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_backend() -> None:
    facade.reset_backend_cache_for_tests()


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
        repositories=["https://example.test/repo.git"],
    )


def _seed_project_with_stories(tmp_path: Path) -> tuple[
    StateBackendPlanningStoryRepository,
    StateBackendStoryDependencyRepository,
]:
    """Seed two stories via the canonical path (AG3-050).

    The ``story_dependencies`` FK now references the STATIC ``stories``
    stammdaten (FK-02 §2.11.3), so the edge endpoints must exist there —
    they are created via ``StoryService.create_story``. The matching
    ``story_contexts`` runtime rows are seeded too because execution
    planning reads the runtime projection.
    """
    project_repository = StateBackendProjectRepository(tmp_path)
    story_context_repository = StateBackendStoryContextRepository(tmp_path)
    project_repository.save(create_project(
        "tenant-a",
        "Tenant A",
        "AK3",
        _configuration(),
        repositories=["https://example.test/repo.git"],
    ))
    service = StoryService(
        story_repository=StateBackendStoryRepository(tmp_path),
        project_repository=project_repository,
        idempotency_repository=StateBackendIdempotencyKeyRepository(tmp_path),
        event_emitter=lambda *_: None,
    )
    for idx, title in enumerate(("One", "Two"), start=1):
        created = service.create_story(
            CreateStoryInput(
                project_key="tenant-a",
                title=title,
                type=WireStoryType.IMPLEMENTATION,
                repos=["https://example.test/repo.git"],
            ),
            op_id=f"op-seed-{idx}",
        )
        story_context_repository.save(
            StoryContext(
                project_key="tenant-a",
                story_number=created.story_number,
                story_id=created.story_display_id,
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
                title=title,
                created_at=datetime.now(UTC),
            ),
        )
    return (
        StateBackendPlanningStoryRepository(tmp_path),
        StateBackendStoryDependencyRepository(tmp_path),
    )


def test_story_dependency_repository_roundtrip(tmp_path: Path) -> None:
    story_repository, dependency_repository = _seed_project_with_stories(tmp_path)

    edge = add_dependency(
        story_id="AK3-002",
        depends_on_story_id="AK3-001",
        kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
        project_key="tenant-a",
        story_repo=story_repository,
        dep_repo=dependency_repository,
    )

    assert dependency_repository.list_for_project("tenant-a") == [edge]
    assert dependency_repository.list_for_story("AK3-002") == [edge]
    with pytest.raises(StoryDependencyConflictError):
        dependency_repository.add(edge, project_key="tenant-a")
    dependency_repository.remove("AK3-002", "AK3-001", StoryDependencyKind.HARD_STORY_DEPENDENCY)
    assert dependency_repository.list_for_project("tenant-a") == []


def test_parallelization_config_repository_roundtrip(tmp_path: Path) -> None:
    project_repository = StateBackendProjectRepository(tmp_path)
    project_repository.save(create_project(
        "tenant-a",
        "Tenant A",
        "AK3",
        _configuration(),
        repositories=["https://example.test/repo.git"],
    ))
    repository = StateBackendParallelizationConfigRepository(tmp_path)
    config = ParallelizationConfig(
        project_key="tenant-a",
        max_parallel_stories=3,
        max_parallel_stories_per_repo=2,
    )

    repository.upsert(config)

    assert repository.get("tenant-a") == config
