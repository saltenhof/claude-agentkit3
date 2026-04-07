"""Core data model for the workflow DSL.

Defines the immutable (frozen) data structures that describe workflow
topology: phases, transitions, guards, gates, yield points, and hooks.
These are pure value objects -- they describe WHAT is allowed, not HOW
it executes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.pipeline.workflow.gates import Gate
    from agentkit.pipeline.workflow.guards import GuardFn
    from agentkit.story.models import PhaseState, StoryContext


@dataclass(frozen=True)
class YieldPoint:
    """A point where the pipeline yields control and waits for external input.

    Yield points model situations like awaiting a design review or
    human approval before resuming execution.

    Args:
        status: The status string to set when yielding (e.g. "awaiting_design_review").
        resume_triggers: Events that can resume execution from this yield point.
        required_artifacts: Artifacts that must be present before resuming.
        timeout_policy: Optional timeout policy name (e.g. "24h", "manual").
    """

    status: str
    resume_triggers: tuple[str, ...] = ()
    required_artifacts: tuple[str, ...] = ()
    timeout_policy: str | None = None


@dataclass(frozen=True)
class HookPoints:
    """Named hook insertion points for workflow lifecycle events.

    Hook names are string references to external hook implementations.
    The workflow definition does not execute hooks -- it only declares
    where they can be attached.

    Args:
        pre_transition: Hooks to run before a transition fires.
        post_transition: Hooks to run after a transition completes.
        on_yield: Hooks to run when the pipeline yields.
        on_escalate: Hooks to run when an escalation occurs.
    """

    pre_transition: tuple[str, ...] = ()
    post_transition: tuple[str, ...] = ()
    on_yield: tuple[str, ...] = ()
    on_escalate: tuple[str, ...] = ()


@dataclass(frozen=True)
class Precondition:
    """A precondition that must be satisfied before entering a phase.

    Args:
        guard: The guard function to evaluate.
        when: Optional callable that determines whether this precondition
            applies. If ``None``, the precondition always applies.
    """

    guard: GuardFn
    when: Callable[[StoryContext, PhaseState], bool] | None = None


@dataclass(frozen=True)
class TransitionRule:
    """A rule describing a valid transition between two phases.

    Multiple transitions with the same ``(source, target)`` but different
    guards are allowed -- the first passing guard wins.

    Args:
        source: Name of the source phase.
        target: Name of the target phase.
        guard: Optional guard that must pass for this transition to fire.
        resume_policy: Optional resume policy name for transitions that
            follow a yield point.
    """

    source: str
    target: str
    guard: GuardFn | None = None
    resume_policy: str | None = None


@dataclass(frozen=True)
class PhaseDefinition:
    """Definition of a single pipeline phase.

    A phase is a named stage in the workflow with optional guards,
    gates, yield points, preconditions, and substates.

    Args:
        name: Unique phase name (e.g. "setup", "verify").
        guards: Guard functions evaluated on phase entry.
        gates: Quality gates that must pass within this phase.
        yield_points: Points where the phase can yield to external input.
        preconditions: Conditions that must hold before entering the phase.
        max_remediation_rounds: Maximum number of remediation attempts
            within this phase (``None`` means no limit from this definition).
        substates: Named sub-states within this phase for fine-grained tracking.
    """

    name: str
    guards: tuple[GuardFn, ...] = ()
    gates: tuple[Gate, ...] = ()
    yield_points: tuple[YieldPoint, ...] = ()
    preconditions: tuple[Precondition, ...] = ()
    max_remediation_rounds: int | None = None
    substates: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowDefinition:
    """Complete immutable workflow definition.

    Describes the full topology of a workflow: which phases exist,
    how they connect via transitions, and what hooks are available.
    This is a pure data object -- it does not execute anything.

    Args:
        name: Human-readable workflow name (e.g. "implementation").
        phases: Ordered tuple of phase definitions.
        transitions: Tuple of transition rules between phases.
        hooks: Hook insertion points for lifecycle events.
    """

    name: str
    phases: tuple[PhaseDefinition, ...] = ()
    transitions: tuple[TransitionRule, ...] = ()
    hooks: HookPoints = field(default_factory=HookPoints)

    def get_phase(self, name: str) -> PhaseDefinition | None:
        """Look up a phase definition by name.

        Args:
            name: The phase name to search for.

        Returns:
            The matching ``PhaseDefinition``, or ``None`` if not found.
        """
        for phase in self.phases:
            if phase.name == name:
                return phase
        return None

    def get_transitions_from(self, phase: str) -> tuple[TransitionRule, ...]:
        """Get all transitions originating from a given phase.

        Args:
            phase: The source phase name.

        Returns:
            Tuple of ``TransitionRule`` objects with matching source.
        """
        return tuple(t for t in self.transitions if t.source == phase)

    @property
    def phase_names(self) -> tuple[str, ...]:
        """Return the ordered tuple of phase names.

        Returns:
            Tuple of phase name strings in definition order.
        """
        return tuple(p.name for p in self.phases)
