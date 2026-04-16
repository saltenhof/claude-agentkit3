"""Fluent builder API for constructing workflow definitions.

The builder is mutable during construction, but produces an immutable
(frozen) ``WorkflowDefinition`` when ``.build()`` is called. This
separation keeps the authoring experience ergonomic while ensuring
the resulting IR is safe for concurrent reads and caching.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from agentkit.exceptions import WorkflowError
from agentkit.pipeline.workflow.model import (
    FlowLevel,
    HookPoints,
    PhaseDefinition,
    Precondition,
    TransitionRule,
    WorkflowDefinition,
    YieldPoint,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.pipeline.workflow.gates import Gate
    from agentkit.pipeline.workflow.guards import GuardFn
    from agentkit.story_context_manager.models import PhaseState, StoryContext


class WorkflowBuilder:
    """Mutable builder that produces an immutable ``WorkflowDefinition``.

    Usage::

        wf = (
            WorkflowBuilder("my-workflow")
            .phase("setup")
            .phase("run")
            .transition("setup", "run")
            .build()
        )

    The builder validates at ``.build()`` time that all transition
    sources and targets reference existing phases, and that at least
    one phase is defined.

    Args:
        name: The workflow name.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._level = FlowLevel.PIPELINE
        self._owner = "PipelineEngine"
        self._phases: list[_PhaseAccumulator] = []
        self._transitions: list[TransitionRule] = []
        self._hooks: HookPoints = HookPoints()
        self._current_phase: _PhaseAccumulator | None = None

    def level(self, level: FlowLevel) -> Self:
        """Set the hierarchy level of the flow being built."""

        self._level = level
        return self

    def owner(self, owner: str) -> Self:
        """Set the logical component owner of the flow."""

        self._owner = owner
        return self

    def phase(self, name: str) -> Self:
        """Register a new phase and set it as the current phase.

        Subsequent calls to ``.guard()``, ``.gate()``, ``.yield_to()``,
        ``.precondition()``, ``.max_remediation_rounds()``, and
        ``.substates()`` apply to this phase.

        Args:
            name: Unique phase name.

        Returns:
            ``self`` for fluent chaining.

        Raises:
            WorkflowError: If a phase with the same name already exists.
        """
        if any(p.name == name for p in self._phases):
            raise WorkflowError(
                f"Duplicate phase name: '{name}'",
                detail={"workflow": self._name, "phase": name},
            )
        acc = _PhaseAccumulator(name=name)
        self._phases.append(acc)
        self._current_phase = acc
        return self

    def guard(self, fn: GuardFn) -> Self:
        """Add a guard to the current phase.

        Args:
            fn: The guard function to add.

        Returns:
            ``self`` for fluent chaining.

        Raises:
            WorkflowError: If no phase has been registered yet.
        """
        self._require_current_phase("guard")
        assert self._current_phase is not None
        self._current_phase.guards.append(fn)
        return self

    def gate(self, gate: Gate) -> Self:
        """Add a quality gate to the current phase.

        Args:
            gate: The gate definition to add.

        Returns:
            ``self`` for fluent chaining.

        Raises:
            WorkflowError: If no phase has been registered yet.
        """
        self._require_current_phase("gate")
        assert self._current_phase is not None
        self._current_phase.gates.append(gate)
        return self

    def yield_to(
        self,
        target: str,
        *,
        on: str,
        resume_triggers: list[str] | None = None,
        required_artifacts: list[str] | None = None,
        timeout_policy: str | None = None,
    ) -> Self:
        """Add a yield point to the current phase.

        A yield point represents a situation where the pipeline pauses
        and waits for external input before resuming.

        Args:
            target: Descriptive name for the yield target (informational).
            on: The status string set when yielding (e.g. "awaiting_design_review").
            resume_triggers: Events that can resume execution.
            required_artifacts: Artifacts that must be present before resuming.
            timeout_policy: Optional timeout policy name.

        Returns:
            ``self`` for fluent chaining.

        Raises:
            WorkflowError: If no phase has been registered yet.
        """
        self._require_current_phase("yield_to")
        assert self._current_phase is not None
        yp = YieldPoint(
            status=on,
            resume_triggers=tuple(resume_triggers) if resume_triggers else (),
            required_artifacts=tuple(required_artifacts) if required_artifacts else (),
            timeout_policy=timeout_policy,
        )
        self._current_phase.yield_points.append(yp)
        return self

    def precondition(
        self,
        fn: GuardFn,
        *,
        when: Callable[[StoryContext, PhaseState], bool] | None = None,
    ) -> Self:
        """Add a precondition to the current phase.

        A precondition is evaluated before entering the phase. If it
        fails, the phase cannot be entered. The optional ``when``
        callable restricts the precondition to specific contexts.

        Args:
            fn: The guard function acting as precondition.
            when: Optional callable determining whether this precondition applies.

        Returns:
            ``self`` for fluent chaining.

        Raises:
            WorkflowError: If no phase has been registered yet.
        """
        self._require_current_phase("precondition")
        assert self._current_phase is not None
        pc = Precondition(guard=fn, when=when)
        self._current_phase.preconditions.append(pc)
        return self

    def max_remediation_rounds(self, n: int) -> Self:
        """Set the maximum remediation rounds for the current phase.

        Args:
            n: Maximum number of remediation attempts.

        Returns:
            ``self`` for fluent chaining.

        Raises:
            WorkflowError: If no phase has been registered yet.
        """
        self._require_current_phase("max_remediation_rounds")
        assert self._current_phase is not None
        self._current_phase.max_remediation_rounds = n
        return self

    def substates(self, states: list[str]) -> Self:
        """Set named sub-states for the current phase.

        Sub-states provide fine-grained tracking within a phase
        (e.g. "merging", "cleanup" within the closure phase).

        Args:
            states: List of sub-state names.

        Returns:
            ``self`` for fluent chaining.

        Raises:
            WorkflowError: If no phase has been registered yet.
        """
        self._require_current_phase("substates")
        assert self._current_phase is not None
        self._current_phase.substates = list(states)
        return self

    def transition(
        self,
        source: str,
        target: str,
        *,
        guard: GuardFn | None = None,
        resume_policy: str | None = None,
    ) -> Self:
        """Add a transition rule between two phases.

        Args:
            source: Name of the source phase.
            target: Name of the target phase.
            guard: Optional guard function for this transition.
            resume_policy: Optional resume policy name.

        Returns:
            ``self`` for fluent chaining.
        """
        tr = TransitionRule(
            source=source,
            target=target,
            guard=guard,
            resume_policy=resume_policy,
        )
        self._transitions.append(tr)
        return self

    def hooks(
        self,
        *,
        pre_transition: list[str] | None = None,
        post_transition: list[str] | None = None,
        on_yield: list[str] | None = None,
        on_escalate: list[str] | None = None,
    ) -> Self:
        """Set workflow-level hook points.

        Hook names are string references to external hook implementations.

        Args:
            pre_transition: Hooks to run before transitions.
            post_transition: Hooks to run after transitions.
            on_yield: Hooks to run when the pipeline yields.
            on_escalate: Hooks to run on escalation.

        Returns:
            ``self`` for fluent chaining.
        """
        self._hooks = HookPoints(
            pre_transition=tuple(pre_transition) if pre_transition else (),
            post_transition=tuple(post_transition) if post_transition else (),
            on_yield=tuple(on_yield) if on_yield else (),
            on_escalate=tuple(on_escalate) if on_escalate else (),
        )
        return self

    def build(self) -> WorkflowDefinition:
        """Validate and produce an immutable ``WorkflowDefinition``.

        Validates that:
        - At least one phase is defined.
        - All transition sources and targets reference existing phases.

        Returns:
            A frozen ``WorkflowDefinition``.

        Raises:
            WorkflowError: If validation fails.
        """
        if not self._phases:
            raise WorkflowError(
                "Cannot build workflow: no phases defined.",
                detail={"workflow": self._name},
            )

        phase_names = {p.name for p in self._phases}

        for tr in self._transitions:
            if tr.source not in phase_names:
                raise WorkflowError(
                    f"Transition source {tr.source!r} is not a defined phase.",
                    detail={
                        "workflow": self._name,
                        "source": tr.source,
                        "target": tr.target,
                        "defined_phases": sorted(phase_names),
                    },
                )
            if tr.target not in phase_names:
                raise WorkflowError(
                    f"Transition target {tr.target!r} is not a defined phase.",
                    detail={
                        "workflow": self._name,
                        "source": tr.source,
                        "target": tr.target,
                        "defined_phases": sorted(phase_names),
                    },
                )

        phases = tuple(p.to_phase_definition() for p in self._phases)
        transitions = tuple(self._transitions)

        return WorkflowDefinition(
            flow_id=self._name,
            level=self._level,
            owner=self._owner,
            nodes=phases,
            edges=transitions,
            hooks=self._hooks,
        )

    def _require_current_phase(self, method: str) -> None:
        """Raise ``WorkflowError`` if no current phase is set.

        Args:
            method: The method name for the error message.

        Raises:
            WorkflowError: If no phase has been registered yet.
        """
        if self._current_phase is None:
            raise WorkflowError(
                f"Cannot call .{method}() before defining a phase with .phase().",
                detail={"workflow": self._name, "method": method},
            )


class _PhaseAccumulator:
    """Internal mutable accumulator for phase data during building.

    Collects guards, gates, yield points, preconditions, substates,
    and remediation settings before being frozen into a ``PhaseDefinition``.

    Args:
        name: The phase name.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.guards: list[GuardFn] = []
        self.gates: list[Gate] = []
        self.yield_points: list[YieldPoint] = []
        self.preconditions: list[Precondition] = []
        self.max_remediation_rounds: int | None = None
        self.substates: list[str] = []

    def to_phase_definition(self) -> PhaseDefinition:
        """Convert to an immutable ``PhaseDefinition``.

        Returns:
            A frozen ``PhaseDefinition`` with all accumulated data.
        """
        return PhaseDefinition(
            name=self.name,
            guards=tuple(self.guards),
            gates=tuple(self.gates),
            yield_points=tuple(self.yield_points),
            preconditions=tuple(self.preconditions),
            max_remediation_rounds=self.max_remediation_rounds,
            substates=tuple(self.substates),
        )


def Workflow(name: str) -> WorkflowBuilder:  # noqa: N802
    """Factory function that creates a new ``WorkflowBuilder``.

    This is a convenience alias for ``WorkflowBuilder(name)`` that
    provides a more concise entry point for workflow definitions.

    Args:
        name: The workflow name.

    Returns:
        A new ``WorkflowBuilder`` instance.
    """
    return WorkflowBuilder(name)
