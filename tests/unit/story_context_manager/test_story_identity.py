from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.project_management.lifecycle import archive_project, create_project
from agentkit.state_backend.store import facade
from agentkit.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.state_backend.store.story_context_repository import (
    StateBackendStoryContextRepository,
)
from agentkit.story_context_manager.errors import (
    StoryIdentityConflictError,
    StoryProjectArchivedError,
    StoryProjectNotFoundError,
)
from agentkit.story_context_manager.lifecycle import create_story
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="https://example.test/repo.git",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
    )


class _ProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[str, Project] = {
            "tenant-a": create_project(
                "tenant-a",
                "Tenant A",
                "AK3",
                _configuration(),
            ),
        }

    def get(self, key: str) -> Project | None:
        return self.projects.get(key)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return list(self.projects.values())

    def save(self, project: Project) -> None:
        self.projects[project.key] = project


class _StoryRepository:
    def __init__(self) -> None:
        self.next_numbers: dict[str, int] = {}
        self.stories: dict[tuple[str, int], StoryContext] = {}
        self.uuids: dict[UUID, StoryContext] = {}

    def allocate_next_story_number(self, project_key: str) -> int:
        next_number = self.next_numbers.get(project_key, 1)
        self.next_numbers[project_key] = next_number + 1
        return next_number

    def get(self, project_key: str, story_id: str) -> StoryContext | None:
        for story in self.stories.values():
            if story.project_key == project_key and story.story_id == story_id:
                return story
        return None

    def get_by_story_number(
        self,
        project_key: str,
        story_number: int,
    ) -> StoryContext | None:
        return self.stories.get((project_key, story_number))

    def get_by_story_uuid(self, story_uuid: UUID) -> StoryContext | None:
        return self.uuids.get(story_uuid)

    def save(self, story: StoryContext) -> None:
        if (
            (story.project_key, story.story_number) in self.stories
            or story.story_uuid in self.uuids
        ):
            raise StoryIdentityConflictError("duplicate story identity")
        self.stories[(story.project_key, story.story_number)] = story
        self.uuids[story.story_uuid] = story


def test_create_story_allocates_next_number_per_project() -> None:
    story_repository = _StoryRepository()
    project_repository = _ProjectRepository()

    first = create_story(
        project_key="tenant-a",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_repository=project_repository,
        story_repository=story_repository,
        title="First story",
    )
    second = create_story(
        project_key="tenant-a",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_repository=project_repository,
        story_repository=story_repository,
        title="Second story",
    )

    assert first.story_number == 1
    assert second.story_number == 2
    assert first.story_id == "AK3-001"
    assert second.story_id == "AK3-002"
    assert first.story_id.endswith(f"-{first.story_number:03d}")


def test_create_story_rejects_archived_project() -> None:
    project_repository = _ProjectRepository()
    project_repository.projects["tenant-a"] = archive_project(
        project_repository.projects["tenant-a"],
        archived_at=datetime(2026, 5, 3, tzinfo=UTC),
    )

    with pytest.raises(StoryProjectArchivedError):
        create_story(
            project_key="tenant-a",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_repository=project_repository,
            story_repository=_StoryRepository(),
        )


def test_create_story_rejects_missing_project() -> None:
    with pytest.raises(StoryProjectNotFoundError):
        create_story(
            project_key="missing",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_repository=_ProjectRepository(),
            story_repository=_StoryRepository(),
        )


def test_state_backend_repository_enforces_story_identity(tmp_path: Path) -> None:
    facade.reset_backend_cache_for_tests()
    project_repository = StateBackendProjectRepository(tmp_path)
    story_repository = StateBackendStoryContextRepository(tmp_path)
    project_repository.save(
        create_project("tenant-a", "Tenant A", "AK3", _configuration()),
    )

    story = create_story(
        project_key="tenant-a",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_repository=project_repository,
        story_repository=story_repository,
    )
    duplicate_number = story.model_copy(
        update={
            "story_uuid": UUID("11111111-1111-1111-1111-111111111111"),
            "story_id": "AK3-999",
        },
    )
    duplicate_uuid = story.model_copy(
        update={
            "story_number": 2,
            "story_id": "AK3-002",
        },
    )

    with pytest.raises(StoryIdentityConflictError):
        story_repository.save(duplicate_number)
    with pytest.raises(StoryIdentityConflictError):
        story_repository.save(duplicate_uuid)


def test_state_backend_allocates_story_numbers_atomically(tmp_path: Path) -> None:
    facade.reset_backend_cache_for_tests()
    project_repository = StateBackendProjectRepository(tmp_path)
    project_repository.save(
        create_project("tenant-a", "Tenant A", "AK3", _configuration()),
    )
    story_repository = StateBackendStoryContextRepository(tmp_path)

    with ThreadPoolExecutor(max_workers=4) as executor:
        numbers = sorted(
            executor.map(
                lambda _: story_repository.allocate_next_story_number("tenant-a"),
                range(6),
            ),
        )

    assert numbers == [1, 2, 3, 4, 5, 6]
