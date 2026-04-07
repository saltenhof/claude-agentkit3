"""Workflow graph validation.

Validates that a ``WorkflowDefinition`` is structurally sound:
reachability, transition consistency, yield point completeness,
and connectivity.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.pipeline.workflow.model import WorkflowDefinition


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
        phase_names = set(workflow.phase_names)

        if not workflow.phases:
            errors.append(ValidationError(
                message="Workflow has no phases defined.",
            ))
            return errors

        first_phase = workflow.phases[0].name
        last_phase = workflow.phases[-1].name

        # (a) Check transition source/target existence
        for tr in workflow.transitions:
            if tr.source not in phase_names:
                errors.append(ValidationError(
                    message=(
                        f"Transition source {tr.source!r} is not a "
                        f"defined phase."
                    ),
                ))
            if tr.target not in phase_names:
                errors.append(ValidationError(
                    message=(
                        f"Transition target {tr.target!r} is not a "
                        f"defined phase."
                    ),
                ))

        # Build adjacency list for reachability analysis
        adjacency: dict[str, set[str]] = defaultdict(set)
        for tr in workflow.transitions:
            if tr.source in phase_names and tr.target in phase_names:
                adjacency[tr.source].add(tr.target)

        # (b) Check reachability from first phase
        reachable = _reachable_from(first_phase, adjacency)
        for phase_name in phase_names:
            if phase_name != first_phase and phase_name not in reachable:
                errors.append(ValidationError(
                    message=(
                        f"Phase {phase_name!r} is not reachable from "
                        f"the first phase {first_phase!r}."
                    ),
                ))

        # (c) At least one transition leads to the last phase
        targets_last = any(
            tr.target == last_phase
            for tr in workflow.transitions
            if tr.source in phase_names and tr.target in phase_names
        )
        if not targets_last and len(workflow.phases) > 1:
            errors.append(ValidationError(
                message=(
                    f"No transition leads to the last phase "
                    f"{last_phase!r}."
                ),
            ))

        # (d) YieldPoints without resume_triggers
        for phase_def in workflow.phases:
            for yp in phase_def.yield_points:
                if not yp.resume_triggers:
                    errors.append(ValidationError(
                        message=(
                            f"YieldPoint {yp.status!r} in phase "
                            f"{phase_def.name!r} has no resume triggers."
                        ),
                    ))

        # (e) Connectivity -- each non-first/last phase needs at least
        #     one incoming or outgoing transition
        incoming: dict[str, int] = defaultdict(int)
        outgoing: dict[str, int] = defaultdict(int)
        for tr in workflow.transitions:
            if tr.source in phase_names and tr.target in phase_names:
                outgoing[tr.source] += 1
                incoming[tr.target] += 1

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
    queue = list(adjacency.get(start, set()))
    while queue:
        node = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        queue.extend(adjacency.get(node, set()) - visited)
    return visited
