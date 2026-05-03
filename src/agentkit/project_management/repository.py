"""Repository protocol for project_management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agentkit.project_management.entities import Project


class ProjectRepository(Protocol):
    """Storage port for project entities."""

    def get(self, key: str) -> Project | None:
        """Return one project or None when it does not exist."""

    def list(self, *, include_archived: bool = False) -> list[Project]:
        """List projects, optionally including archived entries."""

    def save(self, project: Project) -> None:
        """Insert or update one project."""
