"""Repository protocol for project API tokens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agentkit.backend.auth.entities import ProjectApiToken


class ProjectApiTokenRepository(Protocol):
    """Persistence contract for hashed project API tokens."""

    def get(self, token_id: str) -> ProjectApiToken | None:
        """Return one token by id."""

    def get_by_hash(self, token_hash: str) -> ProjectApiToken | None:
        """Return one token by token hash."""

    def list_for_project(self, project_key: str) -> list[ProjectApiToken]:
        """Return all tokens for a project."""

    def save(self, token: ProjectApiToken) -> None:
        """Insert or update a token."""

    def revoke(self, project_key: str, token_id: str) -> None:
        """Mark a token as revoked."""
