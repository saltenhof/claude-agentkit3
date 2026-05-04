"""State-backend story read adapter for execution planning."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.execution_planning.entities import StoryRefForPlanning
from agentkit.execution_planning.lifecycle import PlanningStoryRepository
from agentkit.state_backend.store import facade

if TYPE_CHECKING:
    from agentkit.story_context_manager.models import StoryContext


class StateBackendPlanningStoryRepository(PlanningStoryRepository):
    """Read story summaries for execution-planning calculations."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def get(self, project_key: str, story_id: str) -> StoryRefForPlanning | None:
        story = facade.load_story_context_global(project_key, story_id, self._store_dir)
        if story is None:
            return None
        return _story_ref_from_context(story, store_dir=self._store_dir)

    def list_for_project(self, project_key: str) -> list[StoryRefForPlanning]:
        return [
            _story_ref_from_context(story, store_dir=self._store_dir)
            for story in facade.load_story_contexts_global(project_key, self._store_dir)
        ]


def _story_ref_from_context(
    story: StoryContext,
    *,
    store_dir: Path,
) -> StoryRefForPlanning:
    phase_state = facade.load_phase_state_global(story.story_id, store_dir)
    metrics = facade.load_latest_story_metrics_global(
        story.project_key,
        story.story_id,
        store_dir,
    )
    lifecycle_status = _derive_lifecycle_status(
        phase_status=phase_state.status.value if phase_state is not None else None,
        final_status=metrics.final_status if metrics is not None else None,
    )
    participating_repos = story.participating_repos
    repo = participating_repos[0] if participating_repos else None
    return StoryRefForPlanning(
        project_key=story.project_key,
        story_id=story.story_id,
        story_number=story.story_number,
        title=story.title,
        lifecycle_status=lifecycle_status,
        repo=str(repo) if repo is not None else None,
    )


def _derive_lifecycle_status(
    *,
    phase_status: str | None,
    final_status: str | None,
) -> str:
    if final_status is not None:
        return final_status.lower()
    if phase_status is not None:
        return phase_status
    return "defined"
