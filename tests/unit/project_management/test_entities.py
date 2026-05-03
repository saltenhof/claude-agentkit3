from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.project_management.entities import Project, ProjectConfiguration


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="https://example.test/repo.git",
        default_branch="main",
        are_url=None,
        default_worker_count=2,
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
        )


def test_configuration_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectConfiguration.model_validate(
            {
                "repo_url": "https://example.test/repo.git",
                "default_branch": "main",
                "are_url": None,
                "default_worker_count": 1,
                "unexpected": True,
            },
        )
