"""Project-management read-aggregation service.

Builds the cross-BC ``project_detail`` read model
(``frontend-contracts.entity.project_detail``) for the
``GET /v1/projects/{key}`` endpoint.

Cross-BC boundary (AK7 / architecture-conformance):
  - Project stammdaten come from the project-management
    ``ProjectRepository``.
  - Story-derived data (``mode_lock`` and ``story_counters``) are read
    through the **story_context_manager** ``StoryService`` API
    (``list_stories_with_dependencies``).  project-management does NOT
    touch the story persistence or the dependency store directly — the
    story-counter concept (incl. the ``dependencies`` read-model join used
    for ``ready``/``blocked``) is owned by story_context_manager
    (architecture-conformance group note for BC 17).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from agentkit.backend.project_management.errors import ProjectNotFoundError
from agentkit.backend.project_management.views import (
    ProjectDetailView,
    ProjectModeLock,
    StoryCounters,
)
from agentkit.backend.story_context_manager.story_model import (
    StoryStatus,
    WireStoryMode,
)

if TYPE_CHECKING:
    from agentkit.backend.project_management.entities import Project
    from agentkit.backend.project_management.repository import ProjectRepository
    from agentkit.backend.story_context_manager.story_model import Story


class StoryListPort(Protocol):
    """Structural port for the story-listing dependency.

    Mirrors the subset of ``story_context_manager.StoryService`` used by
    this service.  Production always injects the real ``StoryService``;
    the Protocol keeps the dependency explicit and narrow for tests.

    ``list_stories_with_dependencies`` is the authoritative dependency-aware
    read: it returns stories whose ``dependencies`` read-model join is
    materialized from the story_context_manager dependency store.  This is
    required so the ``ready``/``blocked`` counter classification is correct
    against persisted dependency edges (project-management must NOT read the
    dependency store directly — AK7 cross-BC boundary).
    """

    def list_stories_with_dependencies(self, project_key: str) -> list[Story]:
        """Return all stories of a project with ``dependencies`` filled."""
        ...


class ProjectDetailService:
    """Aggregate the flat ``project_detail`` wire view for a project.

    Args:
        project_repository: Project stammdaten port.  Defaults to the
            state-backend implementation.
        story_service: story_context_manager read service used to obtain
            the project's stories for mode-lock and counter derivation.
            Defaults to the real ``StoryService``.
    """

    def __init__(
        self,
        *,
        project_repository: ProjectRepository | None = None,
        story_service: StoryListPort | None = None,
    ) -> None:
        if project_repository is None:
            from agentkit.backend.state_backend.store.project_management_repository import (
                StateBackendProjectRepository,
            )

            project_repository = StateBackendProjectRepository()
        if story_service is None:
            from agentkit.backend.story_context_manager.service import StoryService

            story_service = StoryService()
        self._projects = project_repository
        self._stories = story_service

    def build_project_detail_view(self, project_key: str) -> ProjectDetailView:
        """Return the flat ``project_detail`` wire view for *project_key*.

        Fail-closed: raises :class:`ProjectNotFoundError` for an unknown
        project (mirrors the 404 path of the project routes).

        Args:
            project_key: Project key to aggregate.

        Returns:
            A fully populated :class:`ProjectDetailView`.

        Raises:
            ProjectNotFoundError: If the project does not exist.
        """
        project = self._projects.get(project_key)
        if project is None:
            raise ProjectNotFoundError(f"Project {project_key!r} not found")

        stories = list(self._stories.list_stories_with_dependencies(project_key))
        return ProjectDetailView(
            project_key=project.key,
            display_name=project.name,
            status=_project_status(project),
            mode_lock=derive_mode_lock(project_key, stories),
            story_counters=compute_story_counters(project_key, stories),
            concept_anchors=[],
        )


def _project_status(project: Project) -> Literal["active", "archived"]:
    return "archived" if project.archived_at is not None else "active"


def derive_mode_lock(project_key: str, stories: list[Story]) -> ProjectModeLock:
    """Derive the project mode-lock from the story corpus (FK-24 §24.3.3).

    Per ``frontend-contracts.invariant.mode_lock_derived``:
      - no ``In Progress`` story            => ``idle``
      - an ``In Progress`` story in ``fast`` => ``fast``
      - otherwise (some ``In Progress``)     => ``standard``

    NOTE (scope AG3-040 sub-block a): persistent per-project mode-lock
    storage does not exist yet (AG3-018 / AG3-034 still open).  The
    derivation below is faithful to the invariant using the wire status
    and per-story ``mode`` carried by the story_context_manager
    ``Story``.

    Args:
        project_key: Project key (echoed into the wire model).
        stories: All stories of the project.

    Returns:
        The derived :class:`ProjectModeLock`.
    """
    in_progress = [s for s in stories if s.status is StoryStatus.IN_PROGRESS]
    mode: Literal["standard", "fast", "idle"]
    if not in_progress:
        mode = "idle"
    elif any(s.mode is WireStoryMode.FAST for s in in_progress):
        mode = "fast"
    else:
        mode = "standard"
    return ProjectModeLock(project_key=project_key, mode=mode)


def compute_story_counters(
    project_key: str,
    stories: list[Story],
) -> StoryCounters:
    """Compute the six story counters per ``counters_classification``.

    Deterministic classification
    (``frontend-contracts.invariant.counters_classification``):
        - total    = |stories|
        - running  = |{status == In Progress}|
        - finished = |{status == Done}|
        - queue    = |{status == Approved}|
        - ready    = |{status == Approved AND blocker is null
                        AND all dependencies in Done}|
        - blocked  = |{status == Backlog}|
                   + |{status == Approved
                        AND (blocker not null OR any dependency not in Done)}|

    Dependencies are story display IDs; "in Done" is evaluated against
    the wire status of the referenced story in the same project corpus.
    An unresolved dependency (absent from the corpus) counts as "not in
    Done", which keeps the Approved story in ``blocked`` (fail-closed).

    Args:
        project_key: Project key (echoed into the wire model).
        stories: All stories of the project.

    Returns:
        The aggregated :class:`StoryCounters`.
    """
    done_ids = {
        s.story_display_id for s in stories if s.status is StoryStatus.DONE
    }

    total = len(stories)
    running = sum(1 for s in stories if s.status is StoryStatus.IN_PROGRESS)
    finished = len(done_ids)
    queue = sum(1 for s in stories if s.status is StoryStatus.APPROVED)

    ready = 0
    blocked = 0
    for story in stories:
        if story.status is StoryStatus.BACKLOG:
            blocked += 1
            continue
        if story.status is not StoryStatus.APPROVED:
            continue
        deps_satisfied = all(dep in done_ids for dep in story.dependencies)
        if story.blocker is None and deps_satisfied:
            ready += 1
        else:
            blocked += 1

    return StoryCounters(
        project_key=project_key,
        total=total,
        finished=finished,
        running=running,
        ready=ready,
        queue=queue,
        blocked=blocked,
    )
