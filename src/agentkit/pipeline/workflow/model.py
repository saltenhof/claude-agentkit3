"""Core data model for the hierarchical process DSL.

The workflow package started as a phase-only pipeline DSL. AK3 now uses
the same control-flow vocabulary for pipelines, phases, components, and
their substeps. This module therefore keeps the existing phase-oriented
API surface intact while introducing the generic terms required by the
concept model:

- ``FlowDefinition`` for any control-flow graph
- ``NodeDefinition`` for a graph node
- ``EdgeRule`` for a directed edge
- ``ExecutionPolicy`` / ``RetryPolicy`` / ``OverridePolicy`` for generic
  runtime semantics

The current engine still interprets the phase-oriented compatibility
surface (``WorkflowDefinition``, ``PhaseDefinition``,
``TransitionRule``). Those names are maintained as aliases over the
generic model so the runtime can evolve without forking the DSL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from agentkit.pipeline.workflow.gates import Gate
    from agentkit.pipeline.workflow.guards import GuardFn
    from agentkit.story_context_manager.models import PhaseState, StoryContext


class FlowLevel(StrEnum):
    """Hierarchy level of a flow definition."""

    PIPELINE = "pipeline"
    PHASE = "phase"
    COMPONENT = "component"


class NodeKind(StrEnum):
    """Generic node kinds shared by all flow levels."""

    STEP = "step"
    GATE = "gate"
    YIELD = "yield"
    BRANCH = "branch"
    SUBFLOW = "subflow"


class ExecutionPolicy(StrEnum):
    """Runtime execution semantics for a node."""

    ALWAYS = "always"
    ONCE_PER_RUN = "once_per_run"
    ONCE_PER_STORY = "once_per_story"
    UNTIL_SUCCESS = "until_success"
    SKIP_AFTER_SUCCESS = "skip_after_success"


@dataclass(frozen=True)
class RetryPolicy:
    """Retry and backtracking limits for a node.

    Args:
        max_attempts: Maximum number of attempts for this node or loop.
            ``None`` means unbounded from the DSL perspective.
        backtrack_target: Explicit node id to jump back to when retrying.
        cooldown_policy: Optional runtime cooldown hint.
    """

    max_attempts: int | None = None
    backtrack_target: str | None = None
    cooldown_policy: str | None = None


@dataclass(frozen=True)
class OverridePolicy:
    """Allowed manual interventions for a node or flow."""

    allow_skip: bool = False
    allow_force_pass: bool = False
    allow_force_fail: bool = False
    allow_jump: bool = False
    allow_truncate: bool = False
    allow_freeze_retries: bool = False


@dataclass(frozen=True)
class YieldPoint:
    """A point where the pipeline yields control and waits for external input."""

    status: str
    resume_triggers: tuple[str, ...] = ()
    required_artifacts: tuple[str, ...] = ()
    timeout_policy: str | None = None


@dataclass(frozen=True)
class HookPoints:
    """Named hook insertion points for flow lifecycle events."""

    pre_transition: tuple[str, ...] = ()
    post_transition: tuple[str, ...] = ()
    on_yield: tuple[str, ...] = ()
    on_escalate: tuple[str, ...] = ()


@dataclass(frozen=True)
class Precondition:
    """A precondition that must be satisfied before entering a node."""

    guard: GuardFn
    when: Callable[[StoryContext, PhaseState], bool] | None = None


@dataclass(frozen=True)
class NodeDefinition:
    """Definition of a control-flow node.

    The current runtime still uses subflow-style nodes to represent
    pipeline phases. For that reason this generic node also carries the
    legacy phase-specific fields used by the engine today.
    """

    name: str
    kind: NodeKind = NodeKind.SUBFLOW
    handler_ref: str | None = None
    execution_policy: ExecutionPolicy = ExecutionPolicy.ALWAYS
    retry_policy: RetryPolicy | None = None
    override_policy: OverridePolicy = field(default_factory=OverridePolicy)
    guards: tuple[GuardFn, ...] = ()
    gates: tuple[Gate, ...] = ()
    yield_points: tuple[YieldPoint, ...] = ()
    preconditions: tuple[Precondition, ...] = ()
    max_remediation_rounds: int | None = None
    substates: tuple[str, ...] = ()

    @property
    def node_id(self) -> str:
        """Canonical identifier used by the generic DSL."""

        return self.name


@dataclass(frozen=True)
class EdgeRule:
    """A directed edge between two nodes in a flow graph."""

    source: str
    target: str
    guard: GuardFn | None = None
    resume_policy: str | None = None
    priority: int = 0


@dataclass(frozen=True)
class FlowDefinition:
    """Complete immutable flow definition.

    ``FlowDefinition`` is the canonical name in the concepts. The
    compatibility properties ``name``, ``phases`` and ``transitions``
    allow the existing engine to continue consuming the same object.
    """

    flow_id: str
    level: FlowLevel = FlowLevel.PIPELINE
    owner: str = "PipelineEngine"
    nodes: tuple[NodeDefinition, ...] = ()
    edges: tuple[EdgeRule, ...] = ()
    hooks: HookPoints = field(default_factory=HookPoints)

    @property
    def name(self) -> str:
        """Compatibility alias for the previous workflow naming."""

        return self.flow_id

    @property
    def phases(self) -> tuple[NodeDefinition, ...]:
        """Compatibility alias for phase-oriented consumers."""

        return self.nodes

    @property
    def transitions(self) -> tuple[EdgeRule, ...]:
        """Compatibility alias for transition-oriented consumers."""

        return self.edges

    def get_node(self, name: str) -> NodeDefinition | None:
        """Look up a node definition by name."""

        for node in self.nodes:
            if node.name == name:
                return node
        return None

    def get_phase(self, name: str) -> NodeDefinition | None:
        """Compatibility alias for phase lookups."""

        return self.get_node(name)

    def get_edges_from(self, node: str) -> tuple[EdgeRule, ...]:
        """Get all outgoing edges from a node ordered by priority."""

        matches = [edge for edge in self.edges if edge.source == node]
        return tuple(sorted(matches, key=lambda edge: edge.priority, reverse=True))

    def get_transitions_from(self, phase: str) -> tuple[EdgeRule, ...]:
        """Compatibility alias for phase transition lookups."""

        return self.get_edges_from(phase)

    @property
    def node_names(self) -> tuple[str, ...]:
        """Return the ordered tuple of node names."""

        return tuple(node.name for node in self.nodes)

    @property
    def phase_names(self) -> tuple[str, ...]:
        """Compatibility alias for phase-oriented tests and engine code."""

        return self.node_names


@dataclass(frozen=True)
class StepExecutionContext:
    """Immutable runtime view for a single node execution."""

    project_key: str
    story_id: str
    run_id: str
    flow_id: str
    node_id: str
    story_context: StoryContext
    phase_state: PhaseState
    active_overrides: tuple[object, ...] = ()
    artifact_handles: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class StepResult:
    """Result envelope returned by a step or gate handler."""

    outcome: str
    produced_artifacts: tuple[str, ...] = ()
    emitted_events: tuple[str, ...] = ()
    requested_yield: YieldPoint | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict)


class StepHandler(Protocol):
    """Execution contract for a ``step`` node."""

    def __call__(self, context: StepExecutionContext) -> StepResult:
        """Execute a single node and return its result envelope."""


class SubflowProvider(Protocol):
    """Execution contract for a ``subflow`` node."""

    def __call__(
        self,
        context: StepExecutionContext,
    ) -> tuple[FlowDefinition, Mapping[str, StepHandler]]:
        """Return the nested flow and its handler registry."""


class GateRunner(Protocol):
    """Execution contract for a ``gate`` node."""

    def __call__(self, context: StepExecutionContext) -> StepResult:
        """Evaluate the gate and return an aggregated result."""


# Compatibility aliases used throughout the current runtime.
PhaseDefinition = NodeDefinition
TransitionRule = EdgeRule
WorkflowDefinition = FlowDefinition
