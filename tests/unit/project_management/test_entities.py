from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.project_management.errors import ProjectRepositoriesInvalidError
from agentkit.project_management.lifecycle import create_project


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="https://example.test/repo.git",
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
            repo_url="https://example.test/repo.git",
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


def test_configuration_repositories_backfill_from_repo_url_on_direct_construct() -> None:
    """model_validator fires even for direct construction; repo_url is used as backfill."""
    config = ProjectConfiguration(
        repo_url="https://example.test/repo.git",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
        # repositories not given — model_validator backfills from repo_url
    )
    assert config.repositories == ["https://example.test/repo.git"]


def test_configuration_repositories_default_with_empty_repo_url_is_empty() -> None:
    """When repo_url is empty and repositories absent, repositories defaults to []."""
    config = ProjectConfiguration.model_validate(
        {
            "repo_url": "",
            "default_branch": "main",
            "are_url": None,
            "default_worker_count": 1,
            # both absent — cannot derive
        }
    )
    assert config.repositories == []


def test_create_project_rejects_empty_repositories() -> None:
    """create_project enforces min-1 entry at write time."""
    config = ProjectConfiguration(
        repo_url="https://example.test/repo.git",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
        repositories=[],
    )
    with pytest.raises(ProjectRepositoriesInvalidError):
        create_project("proj-a", "Proj A", "PA", config)


def test_configuration_repositories_rejects_empty_string() -> None:
    """A whitespace-only entry in repositories must be rejected."""
    with pytest.raises(ValidationError):
        ProjectConfiguration(
            repo_url="https://example.test/repo.git",
            default_branch="main",
            are_url=None,
            default_worker_count=1,
            repositories=["  "],
        )


def test_configuration_repositories_rejects_duplicates() -> None:
    """Duplicate entries in repositories must be rejected."""
    with pytest.raises(ValidationError):
        ProjectConfiguration(
            repo_url="https://example.test/repo.git",
            default_branch="main",
            are_url=None,
            default_worker_count=1,
            repositories=["repo-a", "repo-a"],
        )


def test_configuration_repositories_accepts_multiple_unique_entries() -> None:
    """Multiple unique, non-empty entries must be accepted."""
    config = ProjectConfiguration(
        repo_url="https://example.test/repo.git",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
        repositories=["repo-a", "repo-b", "repo-c"],
    )
    assert config.repositories == ["repo-a", "repo-b", "repo-c"]


def test_configuration_json_migration_backfills_from_repo_url() -> None:
    """Old record without repositories is backfilled from repo_url via model_validator."""
    config = ProjectConfiguration.model_validate(
        {
            "repo_url": "https://example.test/old.git",
            "default_branch": "main",
            "are_url": None,
            "default_worker_count": 1,
            # 'repositories' intentionally absent — simulates old DB record
        }
    )
    assert config.repositories == ["https://example.test/old.git"]


def test_configuration_json_migration_no_repo_url_gives_empty_list() -> None:
    """Old record without repositories AND without repo_url gives repositories=[] and a warning.

    This is the forward-compat path for legacy bootstrap records that had repo_url=''.
    The schema allows [] for reads; min-1 is enforced at write time (lifecycle/routes).
    """
    config = ProjectConfiguration.model_validate(
        {
            "repo_url": "",
            "default_branch": "main",
            "are_url": None,
            "default_worker_count": 1,
            # 'repositories' absent AND repo_url is empty
        }
    )
    assert config.repositories == []
