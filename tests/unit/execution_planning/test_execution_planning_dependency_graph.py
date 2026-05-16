from __future__ import annotations

from datetime import UTC, datetime

from agentkit.execution_planning.dependency_graph import DependencyGraph
from agentkit.execution_planning.entities import StoryDependency, StoryDependencyKind


def _edge(story_id: str, depends_on: str) -> StoryDependency:
    return StoryDependency(
        story_id=story_id,
        depends_on_story_id=depends_on,
        kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
        created_at=datetime.now(UTC),
    )


def test_transitive_walks_diamond_graph() -> None:
    graph = DependencyGraph(
        [
            _edge("AK3-002", "AK3-001"),
            _edge("AK3-003", "AK3-001"),
            _edge("AK3-004", "AK3-002"),
            _edge("AK3-004", "AK3-003"),
        ],
    )

    assert graph.transitive_predecessors("AK3-004") == {
        "AK3-001",
        "AK3-002",
        "AK3-003",
    }
    assert graph.transitive_successors("AK3-001") == {
        "AK3-002",
        "AK3-003",
        "AK3-004",
    }


def test_cycle_detection_returns_path() -> None:
    graph = DependencyGraph(
        [
            _edge("AK3-002", "AK3-001"),
            _edge("AK3-003", "AK3-002"),
            _edge("AK3-001", "AK3-003"),
        ],
    )

    has_cycle, path = graph.has_cycle()

    assert has_cycle
    assert path[0] == path[-1]


def test_topological_layers_are_stable() -> None:
    graph = DependencyGraph(
        [
            _edge("AK3-003", "AK3-001"),
            _edge("AK3-002", "AK3-001"),
            _edge("AK3-004", "AK3-002"),
            _edge("AK3-004", "AK3-003"),
        ],
    )

    assert graph.topological_layers() == [
        ["AK3-001"],
        ["AK3-002", "AK3-003"],
        ["AK3-004"],
    ]


def test_empty_graph_has_no_cycle_or_layers() -> None:
    graph = DependencyGraph([])

    assert graph.has_cycle() == (False, [])
    assert graph.topological_layers() == []
