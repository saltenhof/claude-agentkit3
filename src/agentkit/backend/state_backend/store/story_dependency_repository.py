"""State-backend repository implementation for execution-planning dependencies."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.execution_planning.errors import (
    StoryDependencyConflictError,
    StoryDependencyNotFoundError,
)
from agentkit.backend.execution_planning.repository import StoryDependencyRepository
from agentkit.backend.state_backend.store import facade

if TYPE_CHECKING:
    from agentkit.backend.execution_planning.entities import (
        StoryDependency,
        StoryDependencyKind,
    )


class StateBackendStoryDependencyRepository(StoryDependencyRepository):
    """Persist story dependency edges through the state-backend facade."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def list_for_project(self, project_key: str) -> list[StoryDependency]:
        return facade.load_story_dependencies(project_key, self._store_dir)

    def list_for_story(self, story_id: str) -> list[StoryDependency]:
        return facade.load_story_dependency_rows_for_story(story_id, self._store_dir)

    def add(self, edge: StoryDependency, *, project_key: str) -> None:
        existing = [
            candidate
            for candidate in self.list_for_project(project_key)
            if candidate.story_id == edge.story_id
            and candidate.depends_on_story_id == edge.depends_on_story_id
            and candidate.kind == edge.kind
        ]
        if existing:
            raise StoryDependencyConflictError("Story dependency already exists")
        facade.save_story_dependency(project_key, edge, self._store_dir)

    def remove(
        self,
        story_id: str,
        depends_on_story_id: str,
        kind: StoryDependencyKind,
    ) -> None:
        removed = facade.delete_story_dependency(
            story_id,
            depends_on_story_id,
            kind,
            self._store_dir,
        )
        if removed == 0:
            raise StoryDependencyNotFoundError("Story dependency not found")
