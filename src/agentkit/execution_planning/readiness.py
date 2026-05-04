"""Pure readiness calculations for execution planning."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.execution_planning.entities import ReadinessAssessment, WaveStory

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.execution_planning.dependency_graph import DependencyGraph
    from agentkit.execution_planning.entities import (
        ParallelizationConfig,
        StoryRefForPlanning,
    )

_DONE_STATUSES = frozenset({"done", "completed", "pass", "pass_with_warnings"})


def compute_readiness(
    graph: DependencyGraph,
    completed_story_ids: set[str],
    all_stories: Sequence[StoryRefForPlanning],
    parallel_config: ParallelizationConfig,
) -> ReadinessAssessment:
    """Compute deterministic next-ready and one-wave-after story sets."""

    stories_by_id = {story.story_id: story for story in all_stories}
    active_stories = [
        story
        for story in all_stories
        if story.story_id not in completed_story_ids
        and story.lifecycle_status.lower() not in _DONE_STATUSES
    ]
    layer_by_story_id = _layer_index_by_story_id(graph, stories_by_id)
    ready_candidates = _ready_stories(
        graph,
        active_stories,
        completed_story_ids,
        layer_by_story_id,
    )
    theoretical_parallelism = len(ready_candidates)
    practical_parallelism = min(
        theoretical_parallelism,
        parallel_config.max_parallel_stories,
    )
    next_ready = ready_candidates[:practical_parallelism]
    completed_after_next_wave = completed_story_ids | {
        story.story_id for story in next_ready
    }
    next_wave_after = [
        story
        for story in _ready_stories(
            graph,
            active_stories,
            completed_after_next_wave,
            layer_by_story_id,
        )
        if story.story_id not in {ready.story_id for ready in next_ready}
    ]
    return ReadinessAssessment(
        next_ready=next_ready,
        next_wave_after=next_wave_after,
        theoretical_parallelism=theoretical_parallelism,
        practical_parallelism=practical_parallelism,
        reason=_reason(
            theoretical_parallelism,
            practical_parallelism,
            parallel_config.max_parallel_stories,
        ),
    )


def completed_story_ids_from_statuses(
    stories: Sequence[StoryRefForPlanning],
) -> set[str]:
    """Derive completed story ids from planning story statuses."""

    return {
        story.story_id
        for story in stories
        if story.lifecycle_status.lower() in _DONE_STATUSES
    }


def _ready_stories(
    graph: DependencyGraph,
    stories: Sequence[StoryRefForPlanning],
    completed_story_ids: set[str],
    layer_by_story_id: dict[str, int],
) -> list[WaveStory]:
    ready: list[WaveStory] = []
    for story in sorted(stories, key=lambda item: (item.story_number, item.story_id)):
        if story.story_id in completed_story_ids:
            continue
        blocked_by = sorted(
            predecessor
            for predecessor in graph.direct_predecessors(story.story_id)
            if predecessor not in completed_story_ids
        )
        ready.append(
            WaveStory(
                story_id=story.story_id,
                story_number=story.story_number,
                title=story.title,
                wave=layer_by_story_id.get(story.story_id, 0),
                is_ready=not blocked_by,
                blocked_by=blocked_by,
            ),
        )
    return [story for story in ready if story.is_ready]


def _layer_index_by_story_id(
    graph: DependencyGraph,
    stories_by_id: dict[str, StoryRefForPlanning],
) -> dict[str, int]:
    layers = graph.topological_layers()
    layer_by_story_id: dict[str, int] = {}
    for index, layer in enumerate(layers):
        for story_id in layer:
            layer_by_story_id[story_id] = index
    for story_id in stories_by_id:
        layer_by_story_id.setdefault(story_id, 0)
    return layer_by_story_id


def _reason(
    theoretical_parallelism: int,
    practical_parallelism: int,
    max_parallel_stories: int,
) -> str:
    if theoretical_parallelism == practical_parallelism:
        return f"{practical_parallelism} ready-Stories selektiert"
    return (
        f"{practical_parallelism} von {theoretical_parallelism} ready-Stories "
        f"selektiert, limitiert durch max_parallel_stories={max_parallel_stories}"
    )
