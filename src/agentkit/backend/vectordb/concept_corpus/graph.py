"""Concept corpus graph (FK-13 §13.9.8).

Builds a deterministic DAG from the SSOT discovery result: nodes are concepts,
edges are ``defers_to`` (scoped), ``parent_of_appendix`` and ``superseded_by``.
The graph is the substrate for the validator (cycles, refs, authority) and the
authority resolver (ranking). It is transport-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:

    from agentkit.concepts.parser import DiscoveryResult


@dataclass(frozen=True)
class GraphNode:
    """One concept node in the corpus graph."""

    concept_id: str
    status: str
    module: str
    doc_kind: str
    is_appendix: bool
    parent_concept_id: str
    authority_scopes: tuple[str, ...]
    defers_to_targets: tuple[str, ...]


@dataclass(frozen=True)
class GraphEdge:
    """One directed edge in the corpus graph."""

    source: str
    target: str
    type: str  # defers_to | parent_of_appendix | superseded_by
    scope: str = ""


@dataclass(frozen=True)
class ConceptGraph:
    """Deterministic corpus graph (FK-13 §13.9.8)."""

    nodes: dict[str, GraphNode]
    edges: list[GraphEdge]
    corpus_revision: str

    @property
    def concept_count(self) -> int:
        return len(self.nodes)

    @property
    def active_count(self) -> int:
        return sum(1 for n in self.nodes.values() if n.status == "active")

    def node(self, concept_id: str) -> GraphNode | None:
        return self.nodes.get(concept_id)

    def exists(self, concept_id: str) -> bool:
        return concept_id in self.nodes

    def is_core(self, concept_id: str) -> bool:
        node = self.nodes.get(concept_id)
        return node is not None and not node.is_appendix

    def successors(self, concept_id: str, edge_type: str) -> list[str]:
        return [
            e.target for e in self.edges if e.source == concept_id and e.type == edge_type
        ]


def build_graph(discovery: DiscoveryResult) -> ConceptGraph:
    """Build a :class:`ConceptGraph` from the SSOT discovery result."""
    nodes: dict[str, GraphNode] = {}
    for doc in discovery.documents:
        nodes[doc.concept_id] = GraphNode(
            concept_id=doc.concept_id,
            status=doc.effective_status,
            module=doc.module,
            doc_kind=doc.doc_kind,
            is_appendix=doc.is_appendix,
            parent_concept_id=doc.parent_concept_id,
            authority_scopes=doc.authority_scopes,
            defers_to_targets=doc.defers_to_targets,
        )
    edges: list[GraphEdge] = []
    for doc in discovery.documents:
        for target, scope, _reason in doc.defers_to_full:
            edges.append(GraphEdge(source=doc.concept_id, target=target, type="defers_to", scope=scope))
        if doc.is_appendix and doc.parent_concept_id:
            edges.append(
                GraphEdge(source=doc.concept_id, target=doc.parent_concept_id, type="parent_of_appendix")
            )
        if doc.superseded_by:
            edges.append(
                GraphEdge(source=doc.concept_id, target=doc.superseded_by, type="superseded_by")
            )
    return ConceptGraph(nodes=nodes, edges=edges, corpus_revision=discovery.corpus_revision)


def detect_cycle(graph: ConceptGraph, edge_type: str, *, same_scope: bool = False) -> list[str] | None:
    """Return a cycle path for ``edge_type`` edges, or ``None`` if acyclic.

    When ``same_scope`` is set (E-CYCLE-001), only edges sharing a scope count
    as a back-edge (FK-13 §13.9.7).
    """
    adj: dict[str, list[tuple[str, str]]] = {}
    for edge in graph.edges:
        if edge.type != edge_type:
            continue
        adj.setdefault(edge.source, []).append((edge.target, edge.scope))

    visited: set[str] = set()
    stack: set[str] = set()
    path: list[str] = []

    for start in sorted(graph.nodes):
        if start not in visited:
            result = _walk_cycle(
                start,
                graph=graph,
                adjacency=adj,
                visited=visited,
                stack=stack,
                path=path,
                same_scope=same_scope,
            )
            if result is not None:
                return result
    return None


def _walk_cycle(
    node: str,
    *,
    graph: ConceptGraph,
    adjacency: dict[str, list[tuple[str, str]]],
    visited: set[str],
    stack: set[str],
    path: list[str],
    same_scope: bool,
) -> list[str] | None:
    visited.add(node)
    stack.add(node)
    path.append(node)
    for target, _scope in adjacency.get(node, []):
        if target not in graph.nodes:
            continue
        if target in stack:
            cycle = path[path.index(target) :] + [target]
            if not same_scope or _cycle_has_consistent_scope(cycle, adjacency):
                return cycle
            continue
        if target in visited:
            continue
        found = _walk_cycle(
            target,
            graph=graph,
            adjacency=adjacency,
            visited=visited,
            stack=stack,
            path=path,
            same_scope=same_scope,
        )
        if found is not None:
            return found
    path.pop()
    stack.discard(node)
    return None


def _cycle_has_consistent_scope(cycle: list[str], adj: dict[str, list[tuple[str, str]]]) -> bool:
    """A defers_to cycle counts (E-CYCLE-001) when all edges share one scope."""
    scopes: set[str] = set()
    for i in range(len(cycle) - 1):
        src, dst = cycle[i], cycle[i + 1]
        for target, scope in adj.get(src, []):
            if target == dst:
                scopes.add(scope)
    return len(scopes) == 1 and next(iter(scopes)) != ""


__all__ = [
    "ConceptGraph",
    "GraphEdge",
    "GraphNode",
    "build_graph",
    "detect_cycle",
]
