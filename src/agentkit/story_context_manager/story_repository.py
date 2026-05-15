"""Repository protocol for the Story stammdaten entity.

This is the component-specific repository contract for
``story_context_manager``. It does NOT expose a generic
``state_backend.store`` facade (Architecture-Conformance AC003/AC004).

Implementations:
  - ``InMemoryStoryRepository``: in-process, for unit tests.
  - ``StateBackendStoryRepository``: SQLite/Postgres-backed
    (in ``state_backend/store/story_repository.py``).
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID  # noqa: TC003 (used at runtime in InMemoryStoryRepository)

from agentkit.story_context_manager.story_model import (  # noqa: TC001
    Story,
    StorySpecification,
)


class StoryRepository(Protocol):
    """Storage port for Story stammdaten and StorySpecification."""

    def get_by_display_id(self, story_display_id: str) -> Story | None:
        """Load a Story by its display ID (e.g. ``"AK3-042"``)."""
        ...

    def get_by_uuid(self, story_uuid: UUID) -> Story | None:
        """Load a Story by its technical UUID."""
        ...

    def list_for_project(self, project_key: str) -> list[Story]:
        """Return all Stories for a project, ordered by story_number."""
        ...

    def search(
        self,
        project_key: str,
        query: str,
    ) -> list[Story]:
        """Search Stories for a project by query string.

        Matches against story_display_id, title, participating_repos,
        module, and epic (case-insensitive substring match).
        """
        ...

    def allocate_next_story_number(self, project_key: str) -> int:
        """Atomically allocate the next project-local story number.

        Returns:
            The next available story_number for this project.
            Guaranteed monotone and gap-free under concurrent calls.
        """
        ...

    def save(self, story: Story) -> None:
        """Persist (insert or update) one Story."""
        ...

    def get_specification(
        self, story_uuid: UUID
    ) -> StorySpecification | None:
        """Load the specification for a Story, or None if not present."""
        ...

    def save_specification(
        self,
        story_uuid: UUID,
        spec: StorySpecification,
    ) -> None:
        """Persist (insert or update) one StorySpecification."""
        ...

    def create_story_atomic(
        self,
        story: Story,
        spec: StorySpecification,
        *,
        story_id_prefix: str,
    ) -> None:
        """Atomically allocate a story number and persist story + spec.

        Implementations MUST allocate the story_number, set
        ``story.story_number`` and ``story.story_display_id`` on the
        caller's Story object, then persist Story + StorySpecification
        within a single database transaction.

        Args:
            story: The Story entity (story_number/story_display_id are
                mutated in-place).
            spec: The default StorySpecification to persist.
            story_id_prefix: Project story-ID prefix (e.g. ``"AK3"``).
        """
        ...


# ---------------------------------------------------------------------------
# In-memory implementation (for unit tests — NOT a mock)
# ---------------------------------------------------------------------------


class InMemoryStoryRepository:
    """In-memory story repository — first-class test implementation.

    Supports concurrent story_number allocation via a simple counter.
    NOT thread-safe for concurrent saves; use the SQLite/Postgres
    implementation for integration tests requiring real concurrency.
    """

    def __init__(self) -> None:
        self._stories: dict[str, Story] = {}  # keyed by story_display_id
        self._by_uuid: dict[UUID, Story] = {}
        self._specs: dict[UUID, StorySpecification] = {}
        self._next_numbers: dict[str, int] = {}

    def get_by_display_id(self, story_display_id: str) -> Story | None:
        return self._stories.get(story_display_id)

    def get_by_uuid(self, story_uuid: UUID) -> Story | None:
        return self._by_uuid.get(story_uuid)

    def list_for_project(self, project_key: str) -> list[Story]:
        return sorted(
            (s for s in self._stories.values() if s.project_key == project_key),
            key=lambda s: s.story_number,
        )

    def search(self, project_key: str, query: str) -> list[Story]:
        q = query.lower()
        result: list[Story] = []
        for story in self._stories.values():
            if story.project_key != project_key:
                continue
            if (
                q in story.story_display_id.lower()
                or q in story.title.lower()
                or q in story.module.lower()
                or q in story.epic.lower()
                or any(q in repo.lower() for repo in story.participating_repos)
            ):
                result.append(story)
        return sorted(result, key=lambda s: s.story_number)

    def allocate_next_story_number(self, project_key: str) -> int:
        next_n = self._next_numbers.get(project_key, 1)
        self._next_numbers[project_key] = next_n + 1
        return next_n

    def save(self, story: Story) -> None:
        self._stories[story.story_display_id] = story
        self._by_uuid[story.story_uuid] = story

    def get_specification(self, story_uuid: UUID) -> StorySpecification | None:
        return self._specs.get(story_uuid)

    def save_specification(
        self,
        story_uuid: UUID,
        spec: StorySpecification,
    ) -> None:
        self._specs[story_uuid] = spec

    def create_story_atomic(
        self,
        story: Story,
        spec: StorySpecification,
        *,
        story_id_prefix: str,
    ) -> None:
        """Allocate story_number, patch story in-place, and save story + spec."""
        next_n = self._next_numbers.get(story.project_key, 1)
        self._next_numbers[story.project_key] = next_n + 1
        story.story_number = next_n
        story.story_display_id = f"{story_id_prefix}-{next_n}"
        self.save(story)
        self.save_specification(story.story_uuid, spec)
