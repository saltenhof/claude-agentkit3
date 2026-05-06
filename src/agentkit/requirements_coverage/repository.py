"""Repository protocols for requirements_coverage."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agentkit.requirements_coverage.models import StoryAreLink, StoryAreLinkKind


class StoryAreLinkRepository(Protocol):
    """Storage port for Story-to-ARE edges."""

    def add(self, link: StoryAreLink) -> None:
        """Persist one StoryAreLink edge."""

    def update_kind(
        self,
        story_id: str,
        are_item_id: str,
        old_kind: StoryAreLinkKind,
        new_kind: StoryAreLinkKind,
    ) -> StoryAreLink:
        """Change the edge kind while keeping story and ARE item immutable."""

    def remove(
        self,
        story_id: str,
        are_item_id: str,
        kind: StoryAreLinkKind,
    ) -> None:
        """Remove one StoryAreLink edge."""

    def list_by_story(self, story_id: str) -> list[StoryAreLink]:
        """List StoryAreLink edges for one story in deterministic order."""
