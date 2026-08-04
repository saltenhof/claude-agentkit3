"""State-backend repository implementation for project API tokens."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from psycopg.errors import UniqueViolation

from agentkit.backend.auth.errors import (
    ProjectApiTokenAlreadyExistsError,
    TokenNotFoundError,
)
from agentkit.backend.auth.repository import ProjectApiTokenRepository
from agentkit.backend.state_backend.project_store import (
    insert_project_api_token,
    load_project_api_token,
    load_project_api_token_by_hash,
    load_project_api_tokens_for_project,
    mark_project_api_token_used,
    revoke_project_api_token,
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

    def insert(self, token: ProjectApiToken) -> None:
        try:
            insert_project_api_token(token, self._store_dir)
        except (sqlite3.IntegrityError, UniqueViolation) as exc:
            raise ProjectApiTokenAlreadyExistsError(
                f"Project API token id is already registered: {token.token_id}",
            ) from exc

    def mark_used(self, token_id: str, *, used_at: datetime) -> None:
        mark_project_api_token_used(token_id, used_at.isoformat(), self._store_dir)

    def revoke(self, project_key: str, token_id: str) -> None:
        token = self.get(token_id)
        if token is None or token.project_key != project_key:
            raise TokenNotFoundError("Project API token not found")
        revoke_project_api_token(token_id, datetime.now(UTC).isoformat(), self._store_dir)
