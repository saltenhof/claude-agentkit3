"""Pure dependency-graph algorithms for execution planning."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING

from agentkit.core_types import StoryDependencyKind

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.execution_planning.entities import StoryDependency

HARD_BLOCKING_DEPENDENCY_KINDS = frozenset(
    {
        StoryDependencyKind.HARD_STORY_DEPENDENCY,
        StoryDependencyKind.SERIAL_EXECUTION_CONSTRAINT,
        StoryDependencyKind.MUTEX_CONSTRAINT,
        StoryDependencyKind.SHARED_CONTRACT_DEPENDENCY,
        StoryDependencyKind.SHARED_FILE_CONFLICT,
        StoryDependencyKind.EXTERNAL_DEPENDENCY,
        StoryDependencyKind.HUMAN_GATE_DEPENDENCY,
    },
)


class DependencyGraph:
    """Directed story dependency graph with deterministic DAG algorithms."""

    def __init__(self, edges: Sequence[StoryDependency]) -> None:
        self._nodes: set[str] = set()
        self._successors: dict[str, set[str]] = defaultdict(set)
        self._predecessors: dict[str, set[str]] = defaultdict(set)
        self._predecessor_edges: dict[str, list[StoryDependency]] = defaultdict(list)
        for edge in edges:
            self._nodes.add(edge.story_id)
            self._nodes.add(edge.depends_on_story_id)
            self._successors[edge.depends_on_story_id].add(edge.story_id)
            self._predecessors[edge.story_id].add(edge.depends_on_story_id)
            self._predecessor_edges[edge.story_id].append(edge)

    @property
    def nodes(self) -> set[str]:
        """Return all story ids known to the graph."""

        return set(self._nodes)

    def direct_predecessors(self, story_id: str) -> set[str]:
        """Return direct predecessor story ids for one story."""

        return set(self._predecessors.get(story_id, set()))

    def direct_predecessor_edges(self, story_id: str) -> tuple[StoryDependency, ...]:
        """Return direct predecessor edges with their dependency kind."""

        return tuple(
            sorted(
                self._predecessor_edges.get(story_id, []),
                key=lambda edge: (
                    edge.depends_on_story_id,
                    edge.story_id,
                    edge.kind.value,
                    edge.created_at.isoformat(),
                ),
            ),
        )

    def direct_hard_predecessors(self, story_id: str) -> set[str]:
        """Return direct predecessor ids that block feasibility."""

        return {
            edge.depends_on_story_id
            for edge in self._predecessor_edges.get(story_id, [])
            if edge.kind in HARD_BLOCKING_DEPENDENCY_KINDS
        }

    def transitive_predecessors(self, story_id: str) -> set[str]:
        """Return all predecessor story ids reachable against edge direction."""

        return self._walk(story_id, self._predecessors)

    def transitive_successors(self, story_id: str) -> set[str]:
        """Return all successor story ids reachable along edge direction."""

        return self._walk(story_id, self._successors)

    def has_cycle(self) -> tuple[bool, list[str]]:
        """Return whether the graph has a cycle and a deterministic path."""

        state: dict[str, str] = {}
        stack: list[str] = []

        for node in sorted(self._nodes):
            if state.get(node) is None:
                cycle = self._visit_cycle(node, state, stack)
                if cycle is not None:
                    return True, cycle
        return False, []

    def topological_layers(self) -> list[list[str]]:
        """Return deterministic Kahn layers for a DAG.

        Cyclic graphs return the acyclic prefix only; callers that require a
        full ordering should call :meth:`has_cycle` first.
        """

        indegree = {
            node: len(self._predecessors.get(node, set()))
            for node in self._nodes
        }
        ready = deque(sorted(node for node, degree in indegree.items() if degree == 0))
        layers: list[list[str]] = []
        while ready:
            layer = list(ready)
            ready.clear()
            layers.append(layer)
            next_ready: list[str] = []
            for node in layer:
                for successor in sorted(self._successors.get(node, set())):
                    indegree[successor] -= 1
                    if indegree[successor] == 0:
                        next_ready.append(successor)
            ready.extend(sorted(next_ready))
        return layers

    @staticmethod
    def _walk(start: str, adjacency: dict[str, set[str]]) -> set[str]:
        seen: set[str] = set()
        stack = sorted(adjacency.get(start, set()), reverse=True)
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(sorted(adjacency.get(node, set()), reverse=True))
        return seen

    def _visit_cycle(
        self,
        node: str,
        state: dict[str, str],
        stack: list[str],
    ) -> list[str] | None:
        state[node] = "visiting"
        stack.append(node)
        for successor in sorted(self._successors.get(node, set())):
            cycle = self._cycle_from_successor(successor, state, stack)
            if cycle is not None:
                return cycle
        stack.pop()
        state[node] = "visited"
        return None

    def _cycle_from_successor(
        self,
        successor: str,
        state: dict[str, str],
        stack: list[str],
    ) -> list[str] | None:
        successor_state = state.get(successor)
        if successor_state == "visiting":
            start = stack.index(successor)
            return [*stack[start:], successor]
        if successor_state is None:
            return self._visit_cycle(successor, state, stack)
        return None
