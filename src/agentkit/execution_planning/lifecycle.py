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
    from agentkit.execution_planning.audit import PlanningAuditEmitter
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
    audit: PlanningAuditEmitter | None = None,
) -> ReadinessAssessment:
    """Build the project readiness assessment.

    This is the readiness EVALUATION decision site (FK-70 §70.6.1). When an
    ``audit`` emitter is supplied, the resulting READY/BLOCKED state of each
    evaluated story is emitted as the ``story_ready`` / ``story_blocked`` BC14
    audit events (FK-70 §70.10.3) -- these decisions are genuinely AG3-099-scoped
    (readiness derivation), unlike the scheduling/gate/wave decisions which are
    AG3-100-scoped.

    Args:
        project_key: Tenant/project scope key.
        story_repo: Planning story reader.
        dep_repo: Dependency-edge reader (planning projection path).
        config_repo: Parallelization config reader.
        audit: Optional BC14 audit emitter for ``story_ready``/``story_blocked``.

    Returns:
        The computed ``ReadinessAssessment``.
    """

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
    assessment = compute_readiness(
        DependencyGraph(edges),
        completed_story_ids_from_statuses(stories),
        stories,
        config,
    )
    if audit is not None:
        _emit_readiness_audit(assessment, project_key=project_key, audit=audit)
    return assessment


def _emit_readiness_audit(
    assessment: ReadinessAssessment,
    *,
    project_key: str,
    audit: PlanningAuditEmitter,
) -> None:
    """Emit ``story_ready``/``story_blocked`` for the evaluated readiness result.

    READY stories (the computed ``next_ready`` wave) emit ``story_ready``; the
    blocked stories of the derived plan emit ``story_blocked`` with the dominant
    blocker reason code (FK-70 §70.10.3).
    """
    for wave_story in assessment.next_ready:
        audit.story_ready(story_id=wave_story.story_id, project_key=project_key)
    plan = assessment.plan_derivation
    if plan is None:
        return
    for wave_story in plan.blocked_set:
        reason = (
            wave_story.blocked_by[0].reason_code
            if wave_story.blocked_by
            else "blocked"
        )
        audit.story_blocked(
            story_id=wave_story.story_id,
            reason=reason,
            project_key=project_key,
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
