"""Unit tests for the workflow builder API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.exceptions import WorkflowError
from agentkit.pipeline.workflow.builder import Workflow, WorkflowBuilder
from agentkit.pipeline.workflow.gates import Gate, GateStage
from agentkit.pipeline.workflow.guards import GuardResult
from agentkit.pipeline.workflow.model import WorkflowDefinition

if TYPE_CHECKING:
    from agentkit.story.models import PhaseState, StoryContext


def _trivial_guard(ctx: StoryContext, state: PhaseState) -> GuardResult:
    """Trivial guard that always passes."""
    return GuardResult.PASS()


def _blocking_guard(ctx: StoryContext, state: PhaseState) -> GuardResult:
    """Trivial guard that always fails."""
    return GuardResult.FAIL(reason="blocked")


class TestWorkflowBuilderBasic:
    """Tests for basic builder construction and build()."""

    def test_minimal_workflow_two_phases_one_transition(self) -> None:
        """Minimal workflow with 2 phases and 1 transition builds successfully."""
        wf = (
            Workflow("minimal")
            .phase("start")
            .phase("end")
            .transition("start", "end")
            .build()
        )

        assert isinstance(wf, WorkflowDefinition)
        assert wf.name == "minimal"
        assert wf.phase_names == ("start", "end")
        assert len(wf.transitions) == 1
        assert wf.transitions[0].source == "start"
        assert wf.transitions[0].target == "end"

    def test_build_with_unknown_transition_source_raises(self) -> None:
        """build() raises WorkflowError if transition source is unknown."""
        builder = (
            Workflow("bad")
            .phase("alpha")
            .phase("beta")
            .transition("nonexistent", "beta")
        )

        with pytest.raises(WorkflowError, match="nonexistent"):
            builder.build()

    def test_build_with_unknown_transition_target_raises(self) -> None:
        """build() raises WorkflowError if transition target is unknown."""
        builder = (
            Workflow("bad")
            .phase("alpha")
            .phase("beta")
            .transition("alpha", "nonexistent")
        )

        with pytest.raises(WorkflowError, match="nonexistent"):
            builder.build()

    def test_multiple_build_produces_independent_instances(self) -> None:
        """Multiple build() calls produce independent WorkflowDefinition instances."""
        builder = (
            WorkflowBuilder("multi")
            .phase("a")
            .phase("b")
            .transition("a", "b")
        )

        wf1 = builder.build()
        wf2 = builder.build()

        assert wf1 is not wf2
        assert wf1.name == wf2.name
        assert wf1.phase_names == wf2.phase_names

    def test_builder_without_phases_raises(self) -> None:
        """build() on a builder with no phases raises WorkflowError."""
        builder = WorkflowBuilder("empty")

        with pytest.raises(WorkflowError, match="no phases"):
            builder.build()

    def test_workflow_factory_returns_builder(self) -> None:
        """Workflow() factory returns a WorkflowBuilder instance."""
        builder = Workflow("test")
        assert isinstance(builder, WorkflowBuilder)

    def test_build_rejects_duplicate_phase_names(self) -> None:
        """Builder rejects duplicate phase names."""
        builder = Workflow("test")
        builder.phase("setup")
        with pytest.raises(WorkflowError, match="[Dd]uplicate"):
            builder.phase("setup")


class TestWorkflowBuilderMethods:
    """Tests for individual builder methods: guard, gate, yield_to, etc."""

    def test_guard_added_to_current_phase(self) -> None:
        """guard() adds guard function to the current phase."""
        wf = (
            Workflow("g")
            .phase("start")
            .guard(_trivial_guard)
            .phase("end")
            .transition("start", "end")
            .build()
        )

        start_phase = wf.get_phase("start")
        assert start_phase is not None
        assert len(start_phase.guards) == 1
        assert start_phase.guards[0] is _trivial_guard

    def test_guard_before_phase_raises(self) -> None:
        """guard() without a prior phase() raises WorkflowError."""
        builder = WorkflowBuilder("bad")

        with pytest.raises(WorkflowError, match="guard"):
            builder.guard(_trivial_guard)

    def test_gate_added_to_current_phase(self) -> None:
        """gate() adds gate to the current phase."""
        stage = GateStage(name="check", actor="system")
        gate = Gate(id="test_gate", stages=(stage,))

        wf = (
            Workflow("g")
            .phase("start")
            .gate(gate)
            .phase("end")
            .transition("start", "end")
            .build()
        )

        start_phase = wf.get_phase("start")
        assert start_phase is not None
        assert len(start_phase.gates) == 1
        assert start_phase.gates[0].id == "test_gate"

    def test_gate_before_phase_raises(self) -> None:
        """gate() without a prior phase() raises WorkflowError."""
        builder = WorkflowBuilder("bad")
        stage = GateStage(name="check", actor="system")
        gate = Gate(id="test_gate", stages=(stage,))

        with pytest.raises(WorkflowError, match="gate"):
            builder.gate(gate)

    def test_yield_to_added_to_current_phase(self) -> None:
        """yield_to() adds a YieldPoint to the current phase."""
        wf = (
            Workflow("y")
            .phase("start")
            .yield_to(
                "reviewer",
                on="awaiting_review",
                resume_triggers=["approved"],
                required_artifacts=["review.json"],
                timeout_policy="24h",
            )
            .phase("end")
            .transition("start", "end")
            .build()
        )

        start_phase = wf.get_phase("start")
        assert start_phase is not None
        assert len(start_phase.yield_points) == 1

        yp = start_phase.yield_points[0]
        assert yp.status == "awaiting_review"
        assert yp.resume_triggers == ("approved",)
        assert yp.required_artifacts == ("review.json",)
        assert yp.timeout_policy == "24h"

    def test_yield_to_before_phase_raises(self) -> None:
        """yield_to() without a prior phase() raises WorkflowError."""
        builder = WorkflowBuilder("bad")

        with pytest.raises(WorkflowError, match="yield_to"):
            builder.yield_to("target", on="waiting")

    def test_precondition_added_to_current_phase(self) -> None:
        """precondition() adds a Precondition to the current phase."""
        condition = lambda ctx, state: True  # noqa: E731

        wf = (
            Workflow("p")
            .phase("start")
            .phase("guarded")
            .precondition(_trivial_guard, when=condition)
            .transition("start", "guarded")
            .build()
        )

        guarded = wf.get_phase("guarded")
        assert guarded is not None
        assert len(guarded.preconditions) == 1
        assert guarded.preconditions[0].guard is _trivial_guard
        assert guarded.preconditions[0].when is condition

    def test_precondition_before_phase_raises(self) -> None:
        """precondition() without a prior phase() raises WorkflowError."""
        builder = WorkflowBuilder("bad")

        with pytest.raises(WorkflowError, match="precondition"):
            builder.precondition(_trivial_guard)

    def test_max_remediation_rounds_on_phase(self) -> None:
        """max_remediation_rounds() sets the value on the current phase."""
        wf = (
            Workflow("r")
            .phase("start")
            .max_remediation_rounds(5)
            .phase("end")
            .transition("start", "end")
            .build()
        )

        start = wf.get_phase("start")
        assert start is not None
        assert start.max_remediation_rounds == 5

    def test_max_remediation_rounds_before_phase_raises(self) -> None:
        """max_remediation_rounds() without a prior phase() raises WorkflowError."""
        builder = WorkflowBuilder("bad")

        with pytest.raises(WorkflowError, match="max_remediation_rounds"):
            builder.max_remediation_rounds(3)

    def test_substates_on_phase(self) -> None:
        """substates() sets sub-states on the current phase."""
        wf = (
            Workflow("s")
            .phase("start")
            .substates(["merging", "cleanup", "done"])
            .phase("end")
            .transition("start", "end")
            .build()
        )

        start = wf.get_phase("start")
        assert start is not None
        assert start.substates == ("merging", "cleanup", "done")

    def test_substates_before_phase_raises(self) -> None:
        """substates() without a prior phase() raises WorkflowError."""
        builder = WorkflowBuilder("bad")

        with pytest.raises(WorkflowError, match="substates"):
            builder.substates(["a"])

    def test_hooks_set_on_workflow(self) -> None:
        """hooks() sets workflow-level hook points."""
        wf = (
            Workflow("h")
            .phase("start")
            .phase("end")
            .transition("start", "end")
            .hooks(
                pre_transition=["log"],
                post_transition=["emit"],
                on_yield=["notify"],
                on_escalate=["alert"],
            )
            .build()
        )

        assert wf.hooks.pre_transition == ("log",)
        assert wf.hooks.post_transition == ("emit",)
        assert wf.hooks.on_yield == ("notify",)
        assert wf.hooks.on_escalate == ("alert",)

    def test_transition_with_guard(self) -> None:
        """transition() accepts a guard function."""
        wf = (
            Workflow("t")
            .phase("a")
            .phase("b")
            .transition("a", "b", guard=_trivial_guard)
            .build()
        )

        assert wf.transitions[0].guard is _trivial_guard

    def test_transition_with_resume_policy(self) -> None:
        """transition() accepts a resume_policy string."""
        wf = (
            Workflow("t")
            .phase("a")
            .phase("b")
            .transition("a", "b", resume_policy="remediation")
            .build()
        )

        assert wf.transitions[0].resume_policy == "remediation"
