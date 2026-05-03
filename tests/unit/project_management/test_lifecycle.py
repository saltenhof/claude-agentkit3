from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.project_management.entities import ProjectConfiguration
from agentkit.project_management.errors import (
    ProjectAlreadyArchivedError,
    ProjectImmutableFieldError,
)
from agentkit.project_management.lifecycle import (
    archive_project,
    create_project,
    update_configuration,
)


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="https://example.test/repo.git",
        default_branch="main",
        are_url=None,
        default_worker_count=2,
    )


def test_create_project_returns_non_archived_project() -> None:
    project = create_project("tenant-a", "Tenant A", "AG3", _configuration())

    assert project.key == "tenant-a"
    assert project.archived_at is None


def test_update_configuration_changes_mutable_fields() -> None:
    project = create_project("tenant-a", "Tenant A", "AG3", _configuration())

    updated = update_configuration(
        project,
        name="Tenant Alpha",
        configuration_updates={"default_worker_count": 4},
    )

    assert updated.name == "Tenant Alpha"
    assert updated.configuration.default_worker_count == 4
    assert updated.key == project.key
    assert updated.story_id_prefix == project.story_id_prefix


@pytest.mark.parametrize("field", ["key", "story_id_prefix"])
def test_update_configuration_rejects_immutable_field_attempt(field: str) -> None:
    project = create_project("tenant-a", "Tenant A", "AG3", _configuration())

    with pytest.raises(ProjectImmutableFieldError):
        update_configuration(project, configuration_updates={field: "changed"})


def test_archive_project_sets_timestamp() -> None:
    project = create_project("tenant-a", "Tenant A", "AG3", _configuration())
    archived_at = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)

    archived = archive_project(project, archived_at=archived_at)

    assert archived.archived_at == archived_at


def test_archive_project_rejects_double_archive() -> None:
    project = create_project("tenant-a", "Tenant A", "AG3", _configuration())
    archived = archive_project(
        project,
        archived_at=datetime(2026, 5, 3, 10, 0, tzinfo=UTC),
    )

    with pytest.raises(ProjectAlreadyArchivedError):
        archive_project(archived, archived_at=datetime(2026, 5, 3, 11, 0, tzinfo=UTC))
