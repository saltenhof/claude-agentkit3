"""Repository protocol for story_context_manager."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from uuid import UUID

    from agentkit.story_context_manager.models import StoryContext


class StoryContextRepository(Protocol):
    """Storage port for the StoryContext runtime projection.

    AG3-050 (FK-02 §2.11.2, FK-91 §91.1a): story-number allocation is NOT a
    responsibility of this port. The single canonical allocator lives in
    ``StoryRepository`` (the ``stories`` stammdaten path behind
    ``StoryService.create_story``). ``story_contexts`` is the runtime snapshot
    and is populated at Setup from the already-allocated canonical identity;
    it never allocates a (second) number.
    """

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
