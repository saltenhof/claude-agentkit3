from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.auth.entities import ProjectApiToken

if TYPE_CHECKING:
    from pathlib import Path
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.state_backend.store.auth_repository import StateBackendProjectApiTokenRepository
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)


def test_state_backend_project_api_token_repository_roundtrip(tmp_path: Path) -> None:
    project_repo = StateBackendProjectRepository(tmp_path)
    project_repo.save(
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
    repository = StateBackendProjectApiTokenRepository(tmp_path)
    token = ProjectApiToken(
        token_id="token-1",
        project_key="tenant-a",
        label="edge",
        token_hash="hash-1",
        created_at=datetime(2026, 5, 4, 10, 0, tzinfo=UTC),
    )

    repository.save(token)

    assert repository.get("token-1") == token
    assert repository.get_by_hash("hash-1") == token
    assert repository.list_for_project("tenant-a") == [token]
