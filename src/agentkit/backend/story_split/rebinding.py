"""Pure dependency-rebinding planner (``formal.dependency-rebinding.invariants``).

This module derives the deterministic set of edge mutations for a split plan
WITHOUT touching any store. It is the single fail-closed owner of the six formal
invariants:

  - ``mapping_requires_successors_created`` (enforced by the service ordering,
    documented here);
  - ``no_stale_cancelled_target``;
  - ``no_silent_drop``;
  - ``deterministic_target_selection``;
  - ``no_unjustified_fanout``;
  - ``graph_integrity_preserved`` (no duplicate active edges, no cycles).

The service applies the resulting :class:`RebindingPlan` (remove old edges, add
new edges) AFTER successor creation; the planner itself is side-effect free so
its invariants are unit-testable against real edge models.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.backend.core_types import StoryDependencyKind
    from agentkit.backend.execution_planning.entities import StoryDependency


class RebindingError(ValueError):
    """Fail-closed rebinding-invariant violation (no partial mutation)."""


@dataclass(frozen=True)
class EdgeMutation:
    """One concrete edge mutation derived from the plan.

    Attributes:
        story_id: The dependent story whose edge is rebound.
        depends_on_story_id: The predecessor story id of the edge.
        kind: The dependency kind preserved from the removed source edge.
    """

    story_id: str
    depends_on_story_id: str
    kind: StoryDependencyKind


@dataclass(frozen=True)
class RebindingPlan:
    """The deterministic, fully-resolved edge mutation set for a split.

    Attributes:
        removals: Edges to delete (each old edge onto the cancelled source).
        additions: Edges to add (rebound onto declared successors).
    """

    removals: tuple[EdgeMutation, ...]
    additions: tuple[EdgeMutation, ...]


def validate_rebinding_plan(
    *,
    source_story_id: str,
    successor_ids: tuple[str, ...],
    rebinding_entries: tuple[tuple[str, str, tuple[str, ...]], ...],
    existing_edges: tuple[StoryDependency, ...],
) -> None:
    """Validate the full rebinding plan WITHOUT producing mutations (§54.4 gate).

    Runs the identical six-invariant derivation as :func:`plan_rebinding` but
    discards the result. This is the up-front, fail-closed gate the service runs
    BEFORE any mutation (no successors created/exported, source untouched): it
    can be called with the PLAN-LOCAL successor ids, because every invariant
    (``no_silent_drop``, ``no_stale_cancelled_target``,
    ``deterministic_target_selection``, ``no_unjustified_fanout``,
    ``graph_integrity_preserved``) is decided from the declared successor SET and
    the pre-existing edges — none of them needs the real allocated ids. A plan
    that would fail rebinding is therefore rejected before the split mutates
    anything (formal: ``story-split.transition.requested_to_failed``).

    Args:
        source_story_id: The source story id.
        successor_ids: The declared successor ids (plan-local at gate time).
        rebinding_entries: One ``(dependent_story_id, old_dependency,
            new_dependencies)`` triple per plan entry.
        existing_edges: The current dependency edges of the project graph.

    Raises:
        RebindingError: When any of the six formal invariants would be violated.
    """
    plan_rebinding(
        source_story_id=source_story_id,
        successor_ids=successor_ids,
        rebinding_entries=rebinding_entries,
        existing_edges=existing_edges,
    )


def plan_rebinding(
    *,
    source_story_id: str,
    successor_ids: tuple[str, ...],
    rebinding_entries: tuple[tuple[str, str, tuple[str, ...]], ...],
    existing_edges: tuple[StoryDependency, ...],
) -> RebindingPlan:
    """Derive the deterministic rebinding plan and enforce all six invariants.

    Args:
        source_story_id: The cancelled source story id.
        successor_ids: The declared successor story ids (creation order).
        rebinding_entries: One ``(dependent_story_id, old_dependency,
            new_dependencies)`` triple per plan entry.
        existing_edges: The current dependency edges of the project graph.

    Returns:
        The resolved :class:`RebindingPlan` (removals + additions).

    Raises:
        RebindingError: When any of the six formal invariants would be violated.
            The caller MUST treat this as a fail-closed reject with no mutation.
    """
    successor_set = set(successor_ids)
    inbound_to_source = _index_inbound_edges(existing_edges, source_story_id)

    removals: list[EdgeMutation] = []
    additions: list[EdgeMutation] = []
    # Active edge multiset AFTER the plan is applied (for duplicate/cycle checks).
    projected: set[tuple[str, str, str]] = {
        (e.story_id, e.depends_on_story_id, e.kind.value) for e in existing_edges
    }

    handled_dependents: set[str] = set()
    for dependent_story_id, old_dependency, new_dependencies in rebinding_entries:
        source_edges = _validate_rebinding_entry(
            dependent_story_id=dependent_story_id,
            old_dependency=old_dependency,
            new_dependencies=new_dependencies,
            source_story_id=source_story_id,
            successor_set=successor_set,
            inbound_to_source=inbound_to_source,
        )
        handled_dependents.add(dependent_story_id)
        _derive_entry_mutations(
            dependent_story_id=dependent_story_id,
            new_dependencies=new_dependencies,
            source_story_id=source_story_id,
            source_edges=source_edges,
            projected=projected,
            removals=removals,
            additions=additions,
        )

    _assert_no_stale_targets(
        inbound_to_source=inbound_to_source,
        handled_dependents=handled_dependents,
        source_story_id=source_story_id,
    )
    _assert_acyclic(projected)
    return RebindingPlan(removals=tuple(removals), additions=tuple(additions))


def _index_inbound_edges(
    existing_edges: tuple[StoryDependency, ...], source_story_id: str
) -> dict[str, list[StoryDependency]]:
    """Index inbound edges onto the source by dependent story (preserve kind)."""
    inbound_to_source: dict[str, list[StoryDependency]] = {}
    for edge in existing_edges:
        if edge.depends_on_story_id == source_story_id:
            inbound_to_source.setdefault(edge.story_id, []).append(edge)
    return inbound_to_source


def _validate_rebinding_entry(
    *,
    dependent_story_id: str,
    old_dependency: str,
    new_dependencies: tuple[str, ...],
    source_story_id: str,
    successor_set: set[str],
    inbound_to_source: dict[str, list[StoryDependency]],
) -> list[StoryDependency]:
    """Validate one rebinding entry; return its existing inbound source edges.

    Enforces ``old_dependency == source``, ``no_silent_drop`` (the declared old
    edge must exist) and ``no_unjustified_fanout`` (every declared target must be
    a real successor). Raises :class:`RebindingError` on any violation.
    """
    if old_dependency != source_story_id:
        raise RebindingError(
            "rebinding old_dependency must be the cancelled source "
            f"({source_story_id!r}); got {old_dependency!r}",
        )
    source_edges = inbound_to_source.get(dependent_story_id, [])
    if not source_edges:
        raise RebindingError(
            "no_silent_drop: rebinding entry for "
            f"{dependent_story_id!r} declares an old edge onto "
            f"{old_dependency!r} that does not exist",
        )
    # no_unjustified_fanout: more than one successor target requires an
    # explicit plan declaration (which this very list IS); the implicit
    # fanout we must reject is "one declared target silently expanded".
    # Each declared new_dependency must be a real successor.
    for new_dep in new_dependencies:
        if new_dep not in successor_set:
            raise RebindingError(
                "no_unjustified_fanout: rebinding target "
                f"{new_dep!r} is not a declared successor",
            )
    return source_edges


def _derive_entry_mutations(
    *,
    dependent_story_id: str,
    new_dependencies: tuple[str, ...],
    source_story_id: str,
    source_edges: list[StoryDependency],
    projected: set[tuple[str, str, str]],
    removals: list[EdgeMutation],
    additions: list[EdgeMutation],
) -> None:
    """Append the removal/addition mutations for one validated rebinding entry.

    Mutates ``projected``, ``removals`` and ``additions`` in place. Raises
    :class:`RebindingError` if an addition would create a duplicate active edge
    (``graph_integrity_preserved``).
    """
    for old_edge in source_edges:
        removals.append(
            EdgeMutation(
                story_id=old_edge.story_id,
                depends_on_story_id=source_story_id,
                kind=old_edge.kind,
            )
        )
        projected.discard(
            (old_edge.story_id, source_story_id, old_edge.kind.value)
        )
        for new_dep in new_dependencies:
            key = (dependent_story_id, new_dep, old_edge.kind.value)
            if key in projected:
                raise RebindingError(
                    "graph_integrity_preserved: rebinding would create a "
                    f"duplicate active edge {dependent_story_id!r} -> {new_dep!r}",
                )
            projected.add(key)
            additions.append(
                EdgeMutation(
                    story_id=dependent_story_id,
                    depends_on_story_id=new_dep,
                    kind=old_edge.kind,
                )
            )


def _assert_no_stale_targets(
    *,
    inbound_to_source: dict[str, list[StoryDependency]],
    handled_dependents: set[str],
    source_story_id: str,
) -> None:
    """Enforce ``no_stale_cancelled_target`` for every inbound dependent.

    Every dependent that still points at the source must be covered by a
    rebinding entry; an unhandled inbound edge is a stale pointer onto the
    soon-to-be-cancelled story -> fail closed.
    """
    for dependent_story_id in inbound_to_source:
        if dependent_story_id not in handled_dependents:
            raise RebindingError(
                "no_stale_cancelled_target: dependent story "
                f"{dependent_story_id!r} still points at the cancelled source "
                f"{source_story_id!r} but the plan declares no rebinding for it",
            )


def _assert_acyclic(edges: set[tuple[str, str, str]]) -> None:
    """Raise :class:`RebindingError` if the projected edge set has a cycle.

    Edges are ``story_id -> depends_on_story_id``; a cycle in this directed
    relation is an illegal dependency loop (``graph_integrity_preserved``).
    """
    adjacency: dict[str, set[str]] = {}
    for story_id, depends_on, _kind in edges:
        adjacency.setdefault(story_id, set()).add(depends_on)

    visiting: set[str] = set()
    visited: set[str] = set()

    def _walk(node: str, stack: tuple[str, ...]) -> None:
        if node in visited:
            return
        if node in visiting:
            cycle = " -> ".join((*stack, node))
            raise RebindingError(
                f"graph_integrity_preserved: rebinding introduces a cycle ({cycle})",
            )
        visiting.add(node)
        for successor in sorted(adjacency.get(node, ())):
            _walk(successor, (*stack, node))
        visiting.discard(node)
        visited.add(node)

    for node in sorted(adjacency):
        _walk(node, ())


__all__ = [
    "EdgeMutation",
    "RebindingError",
    "RebindingPlan",
    "plan_rebinding",
    "validate_rebinding_plan",
]
