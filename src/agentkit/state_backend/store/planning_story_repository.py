"""State-backend story read adapter for execution planning.

AG3-050 (FK-02 §2.11.3): story existence/identity for planning is resolved
from the STATIC ``stories`` stammdaten (via ``StateBackendStoryRepository``),
**not** from the runtime projection ``story_contexts``. Dependencies are
story content (preconditions known at definition time), not runtime state,
so the dependency-add / planning read path must accept an edge between two
statically existing stories even when no ``StoryContext`` exists yet.

Runtime-derived fields (``lifecycle_status``) are still read from the
runtime side (phase-state / metrics) when present, otherwise they default
to ``"defined"``. The EXISTENCE of a story and the planning edge hang on the
stammdaten; only the derived status enriches from runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.execution_planning.entities import StoryRefForPlanning
from agentkit.execution_planning.lifecycle import PlanningStoryRepository
from agentkit.state_backend.store import facade
from agentkit.state_backend.store.story_repository import StateBackendStoryRepository

if TYPE_CHECKING:
    from agentkit.story_context_manager.story_model import Story


class StateBackendPlanningStoryRepository(PlanningStoryRepository):
    """Read story summaries for execution-planning calculations.

    Backed by the static ``stories`` stammdaten table; the runtime
    projection only contributes the derived ``lifecycle_status``.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()
        self._story_repo = StateBackendStoryRepository(store_dir)

    def get(self, project_key: str, story_id: str) -> StoryRefForPlanning | None:
        story = self._story_repo.get_by_display_id(story_id)
        if story is None or story.project_key != project_key:
            return None
        return self._story_ref_from_stammdaten(story)

    def list_for_project(self, project_key: str) -> list[StoryRefForPlanning]:
        return [
            self._story_ref_from_stammdaten(story)
            for story in self._story_repo.list_for_project(project_key)
        ]

    def _story_ref_from_stammdaten(self, story: Story) -> StoryRefForPlanning:
        lifecycle_status = _derive_lifecycle_status(
            project_key=story.project_key,
            story_display_id=story.story_display_id,
            store_dir=self._store_dir,
        )
        participating_repos = story.participating_repos
        repo = participating_repos[0] if participating_repos else None
        return StoryRefForPlanning(
            project_key=story.project_key,
            story_id=story.story_display_id,
            story_number=story.story_number,
            title=story.title,
            lifecycle_status=lifecycle_status,
            repo=str(repo) if repo is not None else None,
        )


def _derive_lifecycle_status(
    *,
    project_key: str,
    story_display_id: str,
    store_dir: Path,
) -> str:
    """Derive the planning lifecycle status from runtime state if present.

    Existence is owned by the static ``stories`` stammdaten; the runtime
    projection (phase-state / story-metrics) only refines the status when a
    run already exists. Stories without any runtime state default to
    ``"defined"`` so they participate in planning immediately after creation.
    """
    phase_state = facade.load_phase_state_global(story_display_id, store_dir)
    metrics = facade.load_latest_story_metrics_global(
        project_key,
        story_display_id,
        store_dir,
    )
    if metrics is not None:
        return metrics.final_status.lower()
    if phase_state is not None:
        return phase_state.status.value
    return "defined"
