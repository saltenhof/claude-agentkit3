"""State-backend repository implementation for story_context_manager."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.state_backend.store import facade
from agentkit.story_context_manager.errors import StoryIdentityConflictError
from agentkit.story_context_manager.repository import StoryContextRepository

if TYPE_CHECKING:
    from uuid import UUID

    from agentkit.story_context_manager.models import StoryContext


class StateBackendStoryContextRepository(StoryContextRepository):
    """Persist story contexts through the canonical state-backend facade."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def get(self, project_key: str, story_id: str) -> StoryContext | None:
        return facade.load_story_context_global(project_key, story_id, self._store_dir)

    def get_by_story_number(
        self,
        project_key: str,
        story_number: int,
    ) -> StoryContext | None:
        return facade.load_story_context_by_story_number_global(
            self._store_dir,
            project_key,
            story_number,
        )

    def get_by_story_uuid(self, story_uuid: UUID) -> StoryContext | None:
        return facade.load_story_context_by_uuid_global(self._store_dir, story_uuid)

    def save(self, story: StoryContext) -> None:
        existing_number = self.get_by_story_number(
            story.project_key,
            story.story_number,
        )
        if existing_number is not None and existing_number.story_id != story.story_id:
            raise StoryIdentityConflictError(
                "Story number already belongs to this project",
            )
        existing_uuid = self.get_by_story_uuid(story.story_uuid)
        if existing_uuid is not None and existing_uuid.story_id != story.story_id:
            raise StoryIdentityConflictError("Story UUID already exists")
        facade.save_story_context_global(self._store_dir, story)
