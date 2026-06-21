"""Repository protocols for execution_planning."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agentkit.backend.execution_planning.entities import (
        ParallelizationConfig,
        StoryDependency,
        StoryDependencyKind,
    )


class StoryDependencyRepository(Protocol):
    """Storage port for story dependency edges."""

    def list_for_project(self, project_key: str) -> list[StoryDependency]:
        """Load all dependency edges for one project."""

    def list_for_story(self, story_id: str) -> list[StoryDependency]:
        """Load direct predecessor edges for one story."""

    def add(self, edge: StoryDependency, *, project_key: str) -> None:
        """Persist one dependency edge."""

    def remove(
        self,
        story_id: str,
        depends_on_story_id: str,
        kind: StoryDependencyKind,
    ) -> None:
        """Remove one dependency edge."""


class ParallelizationConfigRepository(Protocol):
    """Storage port for project-local planning configuration."""

    def get(self, project_key: str) -> ParallelizationConfig | None:
        """Load one project's parallelization config."""

    def upsert(self, config: ParallelizationConfig) -> None:
        """Insert or replace one project's parallelization config."""
