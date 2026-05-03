"""Repository protocol for story_context_manager."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from uuid import UUID

    from agentkit.story_context_manager.models import StoryContext


class StoryContextRepository(Protocol):
    """Storage port for story identity and context records."""

    def allocate_next_story_number(self, project_key: str) -> int:
        """Atomically allocate the next project-local story number."""

    def get(self, project_key: str, story_id: str) -> StoryContext | None:
        """Load a story by materialized display id."""

    def get_by_story_number(
        self,
        project_key: str,
        story_number: int,
    ) -> StoryContext | None:
        """Load a story by fachliche identity."""

    def get_by_story_uuid(self, story_uuid: UUID) -> StoryContext | None:
        """Load a story by technical identity."""

    def save(self, story: StoryContext) -> None:
        """Persist one story context."""
