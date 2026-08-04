from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.auth.entities import ProjectApiToken
from agentkit.backend.auth.errors import ProjectApiTokenAlreadyExistsError
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.state_backend.store.auth_repository import (
    StateBackendProjectApiTokenRepository,
)
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)


def test_postgres_revoked_token_id_is_permanently_non_reusable(
    postgres_isolated_schema: str,
) -> None:
    del postgres_isolated_schema
    StateBackendProjectRepository().save(
        Project(
            key="tenant-a",
            name="Tenant A",
            story_id_prefix="AG3",
            configuration=ProjectConfiguration(
                repo_url="",
                default_branch="main",
                are_url=None,
                default_worker_count=1,
                repositories=["https://example.test/repo.git"],
            ),
            archived_at=None,
        ),
    )
    repository = StateBackendProjectApiTokenRepository()
    original = ProjectApiToken(
        token_id="never-reusable",
        project_key="tenant-a",
        label="edge",
        token_hash="original-hash",
        created_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    repository.insert(original)
    repository.revoke(original.project_key, original.token_id)

    with pytest.raises(ProjectApiTokenAlreadyExistsError):
        repository.insert(
            original.model_copy(
                update={"token_hash": "replacement-hash", "revoked_at": None},
            ),
        )

    persisted = repository.get(original.token_id)
    assert persisted is not None
    assert persisted.token_hash == original.token_hash
    assert persisted.revoked_at is not None
