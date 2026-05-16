from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.project_management.errors import (
    ProjectAlreadyArchivedError,
    ProjectImmutableFieldError,
    ProjectRepositoriesInvalidError,
)
from agentkit.project_management.lifecycle import (
    archive_project,
    create_project,
    update_configuration,
)

_DEFAULT_REPOS: list[str] = ["https://example.test/repo.git"]


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="",
        default_branch="main",
        are_url=None,
        default_worker_count=2,
        repositories=list(_DEFAULT_REPOS),
    )


def _make_default_project(
    key: str = "tenant-a",
    name: str = "Tenant A",
    prefix: str = "AG3",
) -> Project:
    """Helper: create_project with the default configuration + repositories.

    Centralises the new ``repositories`` mandatory-parameter (AG3-020
    Befund 3 fix) so the tests stay readable.
    """
    return create_project(
        key,
        name,
        prefix,
        _configuration(),
        repositories=list(_DEFAULT_REPOS),
    )


def test_create_project_returns_non_archived_project() -> None:
    project = _make_default_project()

    assert project.key == "tenant-a"
    assert project.archived_at is None


def test_update_configuration_changes_mutable_fields() -> None:
    project = _make_default_project()

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
    project = _make_default_project()

    with pytest.raises(ProjectImmutableFieldError):
        update_configuration(project, configuration_updates={field: "changed"})


def test_archive_project_sets_timestamp() -> None:
    project = _make_default_project()
    archived_at = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)

    archived = archive_project(project, archived_at=archived_at)

    assert archived.archived_at == archived_at


def test_archive_project_rejects_double_archive() -> None:
    project = _make_default_project()
    archived = archive_project(
        project,
        archived_at=datetime(2026, 5, 3, 10, 0, tzinfo=UTC),
    )

    with pytest.raises(ProjectAlreadyArchivedError):
        archive_project(archived, archived_at=datetime(2026, 5, 3, 11, 0, tzinfo=UTC))


# ---------------------------------------------------------------------------
# AG3-020: repositories lifecycle tests
# ---------------------------------------------------------------------------


def test_create_project_persists_repositories() -> None:
    """create_project stores the repositories list in the configuration."""
    project = create_project(
        "tenant-a",
        "Tenant A",
        "AG3",
        _configuration(),
        repositories=list(_DEFAULT_REPOS),
    )

    assert project.configuration.repositories == ["https://example.test/repo.git"]


def test_create_project_with_repositories_override() -> None:
    """The repositories kwarg overrides the configuration's repositories field."""
    base_config = _configuration()
    project = create_project(
        "tenant-a",
        "Tenant A",
        "AG3",
        base_config,
        repositories=["repo-x", "repo-y"],
    )

    assert project.configuration.repositories == ["repo-x", "repo-y"]


def test_create_project_empty_repositories_override_raises() -> None:
    """create_project rejects an empty repositories override.

    The strict schema (Befund 1 fix) prevents direct construction of
    ``ProjectConfiguration(repositories=[])`` — Pydantic raises
    ``ValidationError`` for ``min_length=1``.  The lifecycle's
    ``_validate_repositories_for_write`` still catches the override path
    where callers pass an explicit ``repositories=[]`` keyword.
    """
    base_config = ProjectConfiguration(
        repo_url="",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
        repositories=["https://example.test/repo.git"],
    )
    with pytest.raises((ProjectRepositoriesInvalidError, ValidationError)):
        create_project(
            "tenant-a",
            "Tenant A",
            "AG3",
            base_config,
            repositories=[],
        )


def test_update_configuration_repositories_empty_raises() -> None:
    """update_configuration rejects replacing repositories with empty list.

    The strict ``min_length=1`` schema raises ``ValidationError`` when the
    re-validated configuration would carry an empty repos list.  Both that
    error and the explicit ``ProjectRepositoriesInvalidError`` are accepted.
    """
    project = _make_default_project()

    with pytest.raises((ProjectRepositoriesInvalidError, ValidationError)):
        update_configuration(
            project,
            configuration_updates={"repositories": []},
        )


def test_update_configuration_repositories_replaces_list() -> None:
    """update_configuration can replace repositories with a valid new list."""
    project = _make_default_project()

    updated = update_configuration(
        project,
        configuration_updates={"repositories": ["repo-a", "repo-b"]},
    )

    assert updated.configuration.repositories == ["repo-a", "repo-b"]
