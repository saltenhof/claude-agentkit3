"""Workflow graph validation.

Validates that a ``WorkflowDefinition`` is structurally sound:
reachability, transition consistency, yield point completeness,
and connectivity.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.process.language.model import (
        PhaseDefinition,
        TransitionRule,
        WorkflowDefinition,
    )


@dataclass(frozen=True)
class ValidationError:
    """A single validation error or warning found in a workflow.

    Args:
        message: Human-readable description of the issue.
        severity: Severity level -- "error" or "warning".
    """

    message: str
    severity: str = "error"


class WorkflowValidator:
    """Validates structural integrity of workflow definitions.

    All checks are static -- no state machine execution required.
    Call ``validate()`` with a ``WorkflowDefinition`` to get a list
    of ``ValidationError`` objects (empty list means valid).
    """

    @staticmethod
    def validate(workflow: WorkflowDefinition) -> list[ValidationError]:
        """Run all validation checks on a workflow definition.

        Checks performed:
            (a) Every transition source/target exists as a phase.
            (b) From the first phase, every other phase is reachable.
            (c) At least one transition leads to the last phase.
            (d) No ``YieldPoint`` without at least one ``resume_trigger``.
            (e) No phase without at least one incoming or outgoing
                transition (except the first and last phases).

        Args:
            workflow: The workflow definition to validate.

        Returns:
            List of ``ValidationError`` objects. Empty means valid.
        """
        errors: list[ValidationError] = []

        if not workflow.phases:
            errors.append(ValidationError(
                message="Workflow has no phases defined.",
            ))
            return errors

        phase_names = set(workflow.phase_names)
        first_phase = workflow.phases[0].name
        last_phase = workflow.phases[-1].name

        errors.extend(_validate_transition_endpoints(workflow.transitions, phase_names))

        adjacency = _build_adjacency(workflow.transitions, phase_names)
        errors.extend(_validate_reachability(first_phase, phase_names, adjacency))
        errors.extend(
            _validate_last_phase_transition(
                workflow.transitions,
                phase_names,
                last_phase,
                len(workflow.phases),
            )
        )
        errors.extend(_validate_yield_points(workflow.phases))
        errors.extend(
            _validate_phase_connectivity(
                workflow.transitions,
                phase_names,
                first_phase,
                last_phase,
            )
        )

        return errors


def _validate_transition_endpoints(
    transitions: tuple[TransitionRule, ...],
    phase_names: set[str],
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    for transition in transitions:
        if transition.source not in phase_names:
            errors.append(ValidationError(
                message=(
                    f"Transition source {transition.source!r} is not a "
                    f"defined phase."
                ),
            ))
        if transition.target not in phase_names:
            errors.append(ValidationError(
                message=(
                    f"Transition target {transition.target!r} is not a "
                    f"defined phase."
                ),
            ))
    return errors


def _build_adjacency(
    transitions: tuple[TransitionRule, ...],
    phase_names: set[str],
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for transition in transitions:
        if transition.source in phase_names and transition.target in phase_names:
            adjacency[transition.source].add(transition.target)
    return adjacency


def _validate_reachability(
    first_phase: str,
    phase_names: set[str],
    adjacency: dict[str, set[str]],
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    reachable = _reachable_from(first_phase, adjacency)
    for phase_name in phase_names:
        if phase_name != first_phase and phase_name not in reachable:
            errors.append(ValidationError(
                message=(
                    f"Phase {phase_name!r} is not reachable from "
                    f"the first phase {first_phase!r}."
                ),
            ))
    return errors


def _validate_last_phase_transition(
    transitions: tuple[TransitionRule, ...],
    phase_names: set[str],
    last_phase: str,
    phase_count: int,
) -> list[ValidationError]:
    if phase_count <= 1:
        return []

    targets_last = any(
        transition.target == last_phase
        for transition in transitions
        if transition.source in phase_names and transition.target in phase_names
    )
    if targets_last:
        return []

    return [
        ValidationError(
            message=f"No transition leads to the last phase {last_phase!r}.",
        )
    ]


def _validate_yield_points(
    phases: tuple[PhaseDefinition, ...],
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    for phase_def in phases:
        for yield_point in phase_def.yield_points:
            if not yield_point.resume_triggers:
                errors.append(ValidationError(
                    message=(
                        f"YieldPoint {yield_point.status!r} in phase "
                        f"{phase_def.name!r} has no resume triggers."
                    ),
                ))
    return errors


def _validate_phase_connectivity(
    transitions: tuple[TransitionRule, ...],
    phase_names: set[str],
    first_phase: str,
    last_phase: str,
) -> list[ValidationError]:
    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, int] = defaultdict(int)
    for transition in transitions:
        if transition.source in phase_names and transition.target in phase_names:
            outgoing[transition.source] += 1
            incoming[transition.target] += 1

    errors: list[ValidationError] = []
    for phase_name in phase_names:
        if phase_name in (first_phase, last_phase):
            continue
        if incoming.get(phase_name, 0) == 0 and outgoing.get(phase_name, 0) == 0:
            errors.append(ValidationError(
                message=(
                    f"Phase {phase_name!r} has no incoming or "
                    f"outgoing transitions."
                ),
            ))
    return errors


def _reachable_from(
    start: str,
    adjacency: dict[str, set[str]],
) -> set[str]:
    """Compute all nodes reachable from ``start`` via BFS.

    Args:
        start: The starting node.
        adjacency: Adjacency list mapping each node to its neighbors.

    Returns:
        Set of all reachable nodes (excluding ``start`` itself).
    """
    visited: set[str] = set()
    queue = deque(adjacency.get(start, set()))
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        queue.extend(adjacency.get(node, set()) - visited)
    return visited
