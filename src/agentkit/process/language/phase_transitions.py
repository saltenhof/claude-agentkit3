"""Derived top-level phase transition superset."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from agentkit.pipeline_engine.phase_executor import PhaseName
from agentkit.process.language.definitions import (
    BUGFIX_WORKFLOW,
    CONCEPT_WORKFLOW,
    IMPLEMENTATION_WORKFLOW,
    RESEARCH_WORKFLOW,
)

if TYPE_CHECKING:
    from agentkit.process.language.model import WorkflowDefinition

type PhaseTransitionGraph = Mapping[PhaseName, frozenset[PhaseName]]

_WORKFLOWS: tuple[WorkflowDefinition, ...] = (
    IMPLEMENTATION_WORKFLOW,
    BUGFIX_WORKFLOW,
    CONCEPT_WORKFLOW,
    RESEARCH_WORKFLOW,
)


def _derive_phase_transition_graph(
    workflows: tuple[WorkflowDefinition, ...],
) -> PhaseTransitionGraph:
    graph: dict[PhaseName, set[PhaseName]] = {phase: set() for phase in PhaseName}
    for workflow in workflows:
        for source in workflow.phase_names:
            source_phase = PhaseName(source)
            for edge in workflow.get_transitions_from(source):
                graph[source_phase].add(PhaseName(edge.target))
    return MappingProxyType(
        {source: frozenset(targets) for source, targets in graph.items()}
    )


PHASE_TRANSITION_GRAPH: PhaseTransitionGraph = _derive_phase_transition_graph(
    _WORKFLOWS,
)


def is_valid_phase_transition(
    from_phase: PhaseName | str,
    to_phase: PhaseName | str,
) -> bool:
    """Return whether a top-level phase transition is in the workflow superset."""

    try:
        source = PhaseName(str(from_phase))
        target = PhaseName(str(to_phase))
    except ValueError:
        return False
    if source is target:
        return True
    return target in PHASE_TRANSITION_GRAPH[source]


def allowed_phase_transition_targets(from_phase: PhaseName | str) -> tuple[str, ...]:
    """Return sorted wire values allowed by the derived transition superset."""

    try:
        source = PhaseName(str(from_phase))
    except ValueError:
        return ()
    return tuple(sorted(target.value for target in PHASE_TRANSITION_GRAPH[source]))
