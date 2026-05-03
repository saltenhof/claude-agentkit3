from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.project_management.entities import ProjectConfiguration
from agentkit.project_management.errors import ProjectStoryIdPrefixConflictError
from agentkit.project_management.lifecycle import archive_project, create_project
from agentkit.state_backend.store import facade
from agentkit.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)

if TYPE_CHECKING:
    from pathlib import Path


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="https://example.test/repo.git",
        default_branch="main",
        are_url=None,
        default_worker_count=2,
    )


@pytest.fixture(autouse=True)
def _reset_backend() -> None:
    facade.reset_backend_cache_for_tests()


def test_repository_saves_gets_and_lists_projects(tmp_path: Path) -> None:
    repository = StateBackendProjectRepository(tmp_path)
    project = create_project("tenant-a", "Tenant A", "AG3", _configuration())

    repository.save(project)

    assert repository.get("tenant-a") == project
    assert repository.list() == [project]


def test_repository_excludes_archived_projects_by_default(tmp_path: Path) -> None:
    repository = StateBackendProjectRepository(tmp_path)
    project = create_project("tenant-a", "Tenant A", "AG3", _configuration())
    archived = archive_project(
        project,
        archived_at=datetime(2026, 5, 3, 10, 0, tzinfo=UTC),
    )

    repository.save(archived)

    assert repository.list() == []
    assert repository.list(include_archived=True) == [archived]


def test_repository_rejects_duplicate_story_id_prefix(tmp_path: Path) -> None:
    repository = StateBackendProjectRepository(tmp_path)
    repository.save(create_project("tenant-a", "Tenant A", "AG3", _configuration()))

    with pytest.raises(ProjectStoryIdPrefixConflictError):
        repository.save(create_project("tenant-b", "Tenant B", "AG3", _configuration()))
