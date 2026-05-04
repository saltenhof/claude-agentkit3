from __future__ import annotations

from datetime import UTC, datetime

from agentkit.execution_planning.dependency_graph import DependencyGraph
from agentkit.execution_planning.entities import (
    ParallelizationConfig,
    StoryDependency,
    StoryDependencyKind,
    StoryRefForPlanning,
)
from agentkit.execution_planning.readiness import compute_readiness


def _story(number: int, *, status: str = "defined") -> StoryRefForPlanning:
    return StoryRefForPlanning(
        project_key="tenant-a",
        story_id=f"AK3-{number:03d}",
        story_number=number,
        title=f"Story {number}",
        lifecycle_status=status,
    )


def _edge(story_id: str, depends_on: str) -> StoryDependency:
    return StoryDependency(
        story_id=story_id,
        depends_on_story_id=depends_on,
        kind=StoryDependencyKind.BLOCKS,
        created_at=datetime.now(UTC),
    )


def test_linear_chain_readiness() -> None:
    stories = [_story(1, status="done"), _story(2), _story(3)]
    graph = DependencyGraph([_edge("AK3-002", "AK3-001"), _edge("AK3-003", "AK3-002")])

    result = compute_readiness(
        graph,
        {"AK3-001"},
        stories,
        ParallelizationConfig(project_key="tenant-a", max_parallel_stories=2),
    )

    assert [story.story_id for story in result.next_ready] == ["AK3-002"]
    assert [story.story_id for story in result.next_wave_after] == ["AK3-003"]
    assert result.reason


def test_practical_parallelism_caps_ready_stories() -> None:
    stories = [_story(1), _story(2), _story(3)]

    result = compute_readiness(
        DependencyGraph([]),
        set(),
        stories,
        ParallelizationConfig(project_key="tenant-a", max_parallel_stories=2),
    )

    assert result.theoretical_parallelism == 3
    assert result.practical_parallelism == 2
    assert [story.story_number for story in result.next_ready] == [1, 2]


def test_diamond_next_wave_after() -> None:
    stories = [_story(1, status="done"), _story(2), _story(3), _story(4)]
    graph = DependencyGraph(
        [
            _edge("AK3-002", "AK3-001"),
            _edge("AK3-003", "AK3-001"),
            _edge("AK3-004", "AK3-002"),
            _edge("AK3-004", "AK3-003"),
        ],
    )

    result = compute_readiness(
        graph,
        {"AK3-001"},
        stories,
        ParallelizationConfig(project_key="tenant-a", max_parallel_stories=2),
    )

    assert [story.story_id for story in result.next_ready] == ["AK3-002", "AK3-003"]
    assert [story.story_id for story in result.next_wave_after] == ["AK3-004"]
