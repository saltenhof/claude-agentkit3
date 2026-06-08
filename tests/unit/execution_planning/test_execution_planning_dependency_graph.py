from __future__ import annotations

from datetime import UTC, datetime

from agentkit.execution_planning.dependency_graph import DependencyGraph
from agentkit.execution_planning.entities import StoryDependency, StoryDependencyKind


def _edge(
    story_id: str,
    depends_on: str,
    *,
    kind: StoryDependencyKind = StoryDependencyKind.HARD_STORY_DEPENDENCY,
) -> StoryDependency:
    return StoryDependency(
        story_id=story_id,
        depends_on_story_id=depends_on,
        kind=kind,
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


def test_dependency_graph_preserves_edge_kind_for_feasibility() -> None:
    graph = DependencyGraph(
        [
            _edge(
                "AK3-002",
                "AK3-001",
                kind=StoryDependencyKind.SOFT_STORY_DEPENDENCY,
            ),
            _edge(
                "AK3-002",
                "AK3-003",
                kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            ),
        ],
    )

    edge_kinds = {edge.kind for edge in graph.direct_predecessor_edges("AK3-002")}

    assert edge_kinds == {
        StoryDependencyKind.SOFT_STORY_DEPENDENCY,
        StoryDependencyKind.HARD_STORY_DEPENDENCY,
    }
    assert graph.direct_hard_predecessors("AK3-002") == {"AK3-003"}
