"""Application services for execution planning."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from agentkit.execution_planning.dependency_graph import DependencyGraph
from agentkit.execution_planning.entities import (
    ExecutionWave,
    ExecutionWaveLifecycle,
    ParallelizationConfig,
    ReadinessAssessment,
    StoryDependency,
    StoryDependencyKind,
    StoryRefForPlanning,
)
from agentkit.execution_planning.errors import (
    StoryDependencyConflictError,
    StoryDependencyCycleError,
    StoryDependencyNotFoundError,
)
from agentkit.execution_planning.readiness import (
    completed_story_ids_from_statuses,
    compute_readiness,
)

if TYPE_CHECKING:
    from agentkit.execution_planning.repository import (
        ParallelizationConfigRepository,
        StoryDependencyRepository,
    )


class PlanningStoryRepository(Protocol):
    """Story reader needed by execution planning."""

    def get(self, project_key: str, story_id: str) -> StoryRefForPlanning | None:
        """Load one story for planning."""

    def list_for_project(self, project_key: str) -> list[StoryRefForPlanning]:
        """Load all planning-relevant stories for one project."""


def add_dependency(
    *,
    story_id: str,
    depends_on_story_id: str,
    kind: StoryDependencyKind,
    project_key: str,
    story_repo: PlanningStoryRepository,
    dep_repo: StoryDependencyRepository,
) -> StoryDependency:
    """Validate and add one dependency edge without creating cycles."""

    if story_id == depends_on_story_id:
        raise StoryDependencyConflictError("Story dependency must not point to itself")

    story = story_repo.get(project_key, story_id)
    depends_on = story_repo.get(project_key, depends_on_story_id)
    if story is None or depends_on is None:
        raise StoryDependencyNotFoundError("Dependency endpoint story not found")
    if story.project_key != depends_on.project_key or story.project_key != project_key:
        raise StoryDependencyNotFoundError(
            "Dependency endpoint story not found in project",
        )

    edge = StoryDependency(
        story_id=story_id,
        depends_on_story_id=depends_on_story_id,
        kind=kind,
        created_at=datetime.now(UTC),
    )
    existing_edges = dep_repo.list_for_project(project_key)
    candidate_graph = DependencyGraph([*existing_edges, edge])
    has_cycle, path = candidate_graph.has_cycle()
    if has_cycle:
        raise StoryDependencyCycleError("Story dependency would create a cycle", path=path)

    dep_repo.add(edge, project_key=project_key)
    return edge


def remove_dependency(
    *,
    story_id: str,
    depends_on_story_id: str,
    kind: StoryDependencyKind,
    dep_repo: StoryDependencyRepository,
) -> None:
    """Remove one dependency edge."""

    dep_repo.remove(story_id, depends_on_story_id, kind)


def assess_readiness(
    *,
    project_key: str,
    story_repo: PlanningStoryRepository,
    dep_repo: StoryDependencyRepository,
    config_repo: ParallelizationConfigRepository,
) -> ReadinessAssessment:
    """Build the project readiness assessment."""

    stories = story_repo.list_for_project(project_key)
    edges = dep_repo.list_for_project(project_key)
    config = config_repo.get(project_key)
    if config is None:
        active_story_count = len(
            [
                story
                for story in stories
                if story.lifecycle_status.lower()
                not in {"done", "completed", "pass", "pass_with_warnings"}
            ],
        )
        config = ParallelizationConfig(
            project_key=project_key,
            max_parallel_stories=max(1, active_story_count),
        )
    return compute_readiness(
        DependencyGraph(edges),
        completed_story_ids_from_statuses(stories),
        stories,
        config,
    )


def mark_wave_after_results(
    wave: ExecutionWave,
    *,
    completed_story_ids: set[str],
    failed_story_ids: set[str],
) -> ExecutionWave:
    """Derive the wave lifecycle after pure story result inputs."""

    wave_story_ids = {story.story_id for story in wave.stories}
    if wave_story_ids & failed_story_ids:
        return wave.model_copy(update={"lifecycle": ExecutionWaveLifecycle.COLLAPSED})
    if wave_story_ids and wave_story_ids <= completed_story_ids:
        return wave.model_copy(update={"lifecycle": ExecutionWaveLifecycle.COMPLETED})
    if wave_story_ids & completed_story_ids:
        return wave.model_copy(update={"lifecycle": ExecutionWaveLifecycle.ACTIVE})
    return wave
