"""State-backend repository implementation for project API tokens."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.auth.errors import TokenNotFoundError
from agentkit.backend.auth.repository import ProjectApiTokenRepository
from agentkit.backend.state_backend.project_store import (
    load_project_api_token,
    load_project_api_token_by_hash,
    load_project_api_tokens_for_project,
    save_project_api_token,
)

if TYPE_CHECKING:
    from agentkit.backend.auth.entities import ProjectApiToken


class StateBackendProjectApiTokenRepository(ProjectApiTokenRepository):
    """Persist project API tokens through the project-management store."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def get(self, token_id: str) -> ProjectApiToken | None:
        return load_project_api_token(token_id, self._store_dir)

    def get_by_hash(self, token_hash: str) -> ProjectApiToken | None:
        return load_project_api_token_by_hash(token_hash, self._store_dir)

    def list_for_project(self, project_key: str) -> list[ProjectApiToken]:
        return load_project_api_tokens_for_project(project_key, self._store_dir)

    def save(self, token: ProjectApiToken) -> None:
        save_project_api_token(token, self._store_dir)

    def revoke(self, project_key: str, token_id: str) -> None:
        token = self.get(token_id)
        if token is None or token.project_key != project_key:
            raise TokenNotFoundError("Project API token not found")
        self.save(token.model_copy(update={"revoked_at": datetime.now(UTC)}))
