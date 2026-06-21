"""State-backend repository implementation for project_management."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.project_management.errors import ProjectStoryIdPrefixConflictError
from agentkit.backend.project_management.repository import ProjectRepository
from agentkit.backend.state_backend.store import facade

if TYPE_CHECKING:
    from agentkit.backend.project_management.entities import Project


class StateBackendProjectRepository(ProjectRepository):
    """Persist projects through the canonical state-backend facade."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def get(self, key: str) -> Project | None:
        return facade.load_project(key, self._store_dir)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return facade.load_projects(
            self._store_dir,
            include_archived=include_archived,
        )

    def save(self, project: Project) -> None:
        existing_prefix_owner = facade.load_project_by_story_id_prefix(
            project.story_id_prefix,
            self._store_dir,
        )
        if (
            existing_prefix_owner is not None
            and existing_prefix_owner.key != project.key
        ):
            raise ProjectStoryIdPrefixConflictError(
                "Story-id prefix already belongs to another project",
            )
        existing_project = self.get(project.key)
        if (
            existing_project is not None
            and existing_project.story_id_prefix != project.story_id_prefix
        ):
            raise ProjectStoryIdPrefixConflictError(
                "Project story-id prefix is immutable",
            )
        facade.save_project(project, self._store_dir)
