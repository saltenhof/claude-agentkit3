from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.project_management.errors import ProjectRepositoriesInvalidError
from agentkit.project_management.lifecycle import create_project


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="",
        default_branch="main",
        are_url=None,
        default_worker_count=2,
        repositories=["https://example.test/repo.git"],
    )


def test_project_accepts_valid_identity_fields() -> None:
    project = Project(
        key="tenant-a",
        name="Tenant A",
        story_id_prefix="AG3",
        configuration=_configuration(),
        archived_at=None,
    )

    assert project.key == "tenant-a"
    assert project.story_id_prefix == "AG3"


@pytest.mark.parametrize("key", ["Tenant", "-tenant", "tenant_a", "tenant!"])
def test_project_rejects_invalid_key(key: str) -> None:
    with pytest.raises(ValidationError):
        Project(
            key=key,
            name="Tenant A",
            story_id_prefix="AG3",
            configuration=_configuration(),
            archived_at=None,
        )


@pytest.mark.parametrize("prefix", ["A", "ag3", "AGENTKIT123", "AG-3"])
def test_project_rejects_invalid_story_id_prefix(prefix: str) -> None:
    with pytest.raises(ValidationError):
        Project(
            key="tenant-a",
            name="Tenant A",
            story_id_prefix=prefix,
            configuration=_configuration(),
            archived_at=None,
        )


def test_configuration_rejects_worker_count_below_one() -> None:
    with pytest.raises(ValidationError):
        ProjectConfiguration(
            repo_url="",
            default_branch="main",
            are_url=None,
            default_worker_count=0,
            repositories=["https://example.test/repo.git"],
        )


def test_configuration_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectConfiguration.model_validate(
            {
                "repo_url": "https://example.test/repo.git",
                "default_branch": "main",
                "are_url": None,
                "default_worker_count": 1,
                "repositories": ["https://example.test/repo.git"],
                "unexpected": True,
            },
        )


# ---------------------------------------------------------------------------
# AG3-020: repositories field tests
# ---------------------------------------------------------------------------


def test_configuration_repositories_missing_raises_validation_error() -> None:
    """AG3-020: repositories is mandatory; absence raises ValidationError.

    The earlier permissive default+backfill on the model has been removed
    (Befund 1 from the second review).  Forward-compat for legacy DB rows
    is handled exclusively in the mapper layer.
    """
    with pytest.raises(ValidationError):
        ProjectConfiguration(  # type: ignore[call-arg]
            repo_url="",
            default_branch="main",
            are_url=None,
            default_worker_count=1,
            # repositories intentionally omitted
        )


def test_configuration_repositories_empty_list_raises_validation_error() -> None:
    """AG3-020: repositories=[] is rejected at the schema level (min_length=1)."""
    with pytest.raises(ValidationError):
        ProjectConfiguration(
            repo_url="",
            default_branch="main",
            are_url=None,
            default_worker_count=1,
            repositories=[],
        )


def test_create_project_rejects_empty_repositories_when_override_used() -> None:
    """create_project rejects an empty repositories override at write time."""
    config = ProjectConfiguration(
        repo_url="",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
        repositories=["https://example.test/repo.git"],
    )
    with pytest.raises((ProjectRepositoriesInvalidError, ValidationError)):
        create_project("proj-a", "Proj A", "PA", config, repositories=[])


def test_configuration_repositories_rejects_empty_string() -> None:
    """A whitespace-only entry in repositories must be rejected."""
    with pytest.raises(ValidationError):
        ProjectConfiguration(
            repo_url="",
            default_branch="main",
            are_url=None,
            default_worker_count=1,
            repositories=["  "],
        )


def test_configuration_repositories_rejects_duplicates() -> None:
    """Duplicate entries in repositories must be rejected."""
    with pytest.raises(ValidationError):
        ProjectConfiguration(
            repo_url="",
            default_branch="main",
            are_url=None,
            default_worker_count=1,
            repositories=["repo-a", "repo-a"],
        )


def test_configuration_repositories_accepts_multiple_unique_entries() -> None:
    """Multiple unique, non-empty entries must be accepted."""
    config = ProjectConfiguration(
        repo_url="",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
        repositories=["repo-a", "repo-b", "repo-c"],
    )
    assert config.repositories == ["repo-a", "repo-b", "repo-c"]


def test_configuration_model_rejects_legacy_record_without_repositories() -> None:
    """AG3-020 (second review): the schema is strict.

    Forward-compat for legacy DB rows lives exclusively in the mapper layer
    (see ``state_backend/store/mappers.py::_backfill_legacy_project_configuration_payload``
    and the mapper-level test in ``test_repository.py``).  Bypassing the
    mapper and pushing a legacy-shaped dict directly into ``model_validate``
    MUST fail — that proves the schema is fail-closed.
    """
    with pytest.raises(ValidationError):
        ProjectConfiguration.model_validate(
            {
                "repo_url": "",
                "default_branch": "main",
                "are_url": None,
                "default_worker_count": 1,
                # 'repositories' intentionally absent
            },
        )
