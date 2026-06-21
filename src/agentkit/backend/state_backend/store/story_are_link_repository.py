"""State-backend repository implementation for StoryAreLink edges."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.requirements_coverage.errors import (
    StoryAreLinkConflictError,
    StoryAreLinkNotFoundError,
)
from agentkit.backend.requirements_coverage.repository import StoryAreLinkRepository
from agentkit.backend.state_backend.store import facade

if TYPE_CHECKING:
    from agentkit.backend.requirements_coverage.models import StoryAreLink, StoryAreLinkKind

_NOT_FOUND_MESSAGE = "StoryAreLink not found"


class StateBackendStoryAreLinkRepository(StoryAreLinkRepository):
    """Persist StoryAreLink edges through the canonical state-backend facade."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def add(self, link: StoryAreLink) -> None:
        existing = [
            candidate
            for candidate in self.list_by_story(link.story_id)
            if candidate.are_item_id == link.are_item_id and candidate.kind == link.kind
        ]
        if existing:
            raise StoryAreLinkConflictError("StoryAreLink already exists")
        facade.save_story_are_link(link, self._store_dir)

    def update_kind(
        self,
        story_id: str,
        are_item_id: str,
        old_kind: StoryAreLinkKind,
        new_kind: StoryAreLinkKind,
    ) -> StoryAreLink:
        if old_kind == new_kind:
            current = [
                link
                for link in self.list_by_story(story_id)
                if link.are_item_id == are_item_id and link.kind == old_kind
            ]
            if not current:
                raise StoryAreLinkNotFoundError(_NOT_FOUND_MESSAGE)
            return current[0]

        if any(
            link.are_item_id == are_item_id and link.kind == new_kind
            for link in self.list_by_story(story_id)
        ):
            raise StoryAreLinkConflictError("Target StoryAreLink kind already exists")

        updated = facade.update_story_are_link_kind(
            self._store_dir,
            story_id,
            are_item_id,
            old_kind,
            new_kind,
        )
        if updated is None:
            raise StoryAreLinkNotFoundError(_NOT_FOUND_MESSAGE)
        return updated

    def remove(
        self,
        story_id: str,
        are_item_id: str,
        kind: StoryAreLinkKind,
    ) -> None:
        removed = facade.delete_story_are_link(
            self._store_dir,
            story_id,
            are_item_id,
            kind,
        )
        if removed == 0:
            raise StoryAreLinkNotFoundError(_NOT_FOUND_MESSAGE)

    def list_by_story(self, story_id: str) -> list[StoryAreLink]:
        return facade.load_story_are_links(story_id, self._store_dir)
