"""Unit tests for the workflow data model."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest

from agentkit.pipeline.workflow.gates import Gate
from agentkit.pipeline.workflow.guards import GuardResult
from agentkit.pipeline.workflow.model import (
    HookPoints,
    PhaseDefinition,
    Precondition,
    TransitionRule,
    WorkflowDefinition,
    YieldPoint,
)

if TYPE_CHECKING:
    from agentkit.story.models import PhaseState, StoryContext


class TestYieldPoint:
    """Tests for YieldPoint frozen dataclass."""

    def test_construction_with_defaults(self) -> None:
        yp = YieldPoint(status="awaiting_review")
        assert yp.status == "awaiting_review"
        assert yp.resume_triggers == ()
        assert yp.required_artifacts == ()
        assert yp.timeout_policy is None

    def test_construction_with_all_fields(self) -> None:
        yp = YieldPoint(
            status="awaiting_design_review",
            resume_triggers=("design_approved", "design_rejected"),
            required_artifacts=("design.md",),
            timeout_policy="24h",
        )
        assert yp.status == "awaiting_design_review"
        assert yp.resume_triggers == ("design_approved", "design_rejected")
        assert yp.required_artifacts == ("design.md",)
        assert yp.timeout_policy == "24h"

    def test_frozen(self) -> None:
        yp = YieldPoint(status="test")
        with pytest.raises(dataclasses.FrozenInstanceError):
            yp.status = "modified"  # type: ignore[misc]


class TestHookPoints:
    """Tests for HookPoints frozen dataclass."""

    def test_defaults(self) -> None:
        hp = HookPoints()
        assert hp.pre_transition == ()
        assert hp.post_transition == ()
        assert hp.on_yield == ()
        assert hp.on_escalate == ()

    def test_with_hooks(self) -> None:
        hp = HookPoints(
            pre_transition=("log",),
            post_transition=("emit",),
            on_yield=("notify",),
            on_escalate=("alert",),
        )
        assert hp.pre_transition == ("log",)
        assert hp.post_transition == ("emit",)
        assert hp.on_yield == ("notify",)
        assert hp.on_escalate == ("alert",)

    def test_frozen(self) -> None:
        hp = HookPoints()
        with pytest.raises(dataclasses.FrozenInstanceError):
            hp.pre_transition = ("x",)  # type: ignore[misc]


class TestPrecondition:
    """Tests for Precondition frozen dataclass."""

    def test_construction_guard_only(self) -> None:
        def g(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.PASS()

        pc = Precondition(guard=g)
        assert pc.guard is g
        assert pc.when is None

    def test_construction_with_when(self) -> None:
        def g(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.PASS()

        def w(ctx: StoryContext, state: PhaseState) -> bool:
            return True

        pc = Precondition(guard=g, when=w)
        assert pc.guard is g
        assert pc.when is w

    def test_frozen(self) -> None:
        def g(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.PASS()

        pc = Precondition(guard=g)
        with pytest.raises(dataclasses.FrozenInstanceError):
            pc.guard = g  # type: ignore[misc]


class TestTransitionRule:
    """Tests for TransitionRule frozen dataclass."""

    def test_minimal(self) -> None:
        tr = TransitionRule(source="setup", target="verify")
        assert tr.source == "setup"
        assert tr.target == "verify"
        assert tr.guard is None
        assert tr.resume_policy is None

    def test_with_guard_and_policy(self) -> None:
        def g(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.PASS()

        tr = TransitionRule(
            source="setup",
            target="verify",
            guard=g,
            resume_policy="last_checkpoint",
        )
        assert tr.guard is g
        assert tr.resume_policy == "last_checkpoint"

    def test_frozen(self) -> None:
        tr = TransitionRule(source="a", target="b")
        with pytest.raises(dataclasses.FrozenInstanceError):
            tr.source = "c"  # type: ignore[misc]


class TestPhaseDefinition:
    """Tests for PhaseDefinition frozen dataclass."""

    def test_defaults(self) -> None:
        pd = PhaseDefinition(name="setup")
        assert pd.name == "setup"
        assert pd.guards == ()
        assert pd.gates == ()
        assert pd.yield_points == ()
        assert pd.preconditions == ()
        assert pd.max_remediation_rounds is None
        assert pd.substates == ()

    def test_full_construction(self) -> None:
        def g(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.PASS()

        gate = Gate(id="test_gate")
        yp = YieldPoint(status="waiting")
        pc = Precondition(guard=g)

        pd = PhaseDefinition(
            name="verify",
            guards=(g,),
            gates=(gate,),
            yield_points=(yp,),
            preconditions=(pc,),
            max_remediation_rounds=3,
            substates=("structural", "semantic"),
        )
        assert pd.name == "verify"
        assert len(pd.guards) == 1
        assert len(pd.gates) == 1
        assert len(pd.yield_points) == 1
        assert len(pd.preconditions) == 1
        assert pd.max_remediation_rounds == 3
        assert pd.substates == ("structural", "semantic")

    def test_frozen(self) -> None:
        pd = PhaseDefinition(name="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            pd.name = "y"  # type: ignore[misc]


class TestWorkflowDefinition:
    """Tests for WorkflowDefinition frozen dataclass and helper methods."""

    def test_defaults(self) -> None:
        wd = WorkflowDefinition(name="empty")
        assert wd.name == "empty"
        assert wd.phases == ()
        assert wd.transitions == ()
        assert wd.hooks == HookPoints()

    def test_get_phase_found(self, minimal_workflow: WorkflowDefinition) -> None:
        phase = minimal_workflow.get_phase("start")
        assert phase is not None
        assert phase.name == "start"

    def test_get_phase_not_found(self, minimal_workflow: WorkflowDefinition) -> None:
        phase = minimal_workflow.get_phase("nonexistent")
        assert phase is None

    def test_get_transitions_from(
        self, minimal_workflow: WorkflowDefinition,
    ) -> None:
        transitions = minimal_workflow.get_transitions_from("start")
        assert len(transitions) == 1
        assert transitions[0].target == "end"

    def test_get_transitions_from_no_match(
        self, minimal_workflow: WorkflowDefinition,
    ) -> None:
        transitions = minimal_workflow.get_transitions_from("end")
        assert transitions == ()

    def test_phase_names(self, minimal_workflow: WorkflowDefinition) -> None:
        assert minimal_workflow.phase_names == ("start", "end")

    def test_phase_names_order_preserved(self) -> None:
        wd = WorkflowDefinition(
            name="ordered",
            phases=(
                PhaseDefinition(name="c"),
                PhaseDefinition(name="a"),
                PhaseDefinition(name="b"),
            ),
        )
        assert wd.phase_names == ("c", "a", "b")

    def test_frozen(self, minimal_workflow: WorkflowDefinition) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            minimal_workflow.name = "modified"  # type: ignore[misc]

    def test_multiple_transitions_from_same_source(self) -> None:
        def g1(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.PASS()

        def g2(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.FAIL(reason="nope")

        wd = WorkflowDefinition(
            name="branching",
            phases=(
                PhaseDefinition(name="a"),
                PhaseDefinition(name="b"),
                PhaseDefinition(name="c"),
            ),
            transitions=(
                TransitionRule(source="a", target="b", guard=g1),
                TransitionRule(source="a", target="c", guard=g2),
            ),
        )
        transitions = wd.get_transitions_from("a")
        assert len(transitions) == 2
        assert transitions[0].target == "b"
        assert transitions[1].target == "c"

    def test_three_phase_workflow_structure(
        self, three_phase_workflow: WorkflowDefinition,
    ) -> None:
        assert three_phase_workflow.phase_names == ("alpha", "beta", "gamma")
        assert len(three_phase_workflow.transitions) == 2
        beta = three_phase_workflow.get_phase("beta")
        assert beta is not None
        assert len(beta.guards) == 1
        assert len(beta.gates) == 1
        assert three_phase_workflow.hooks.pre_transition == ("log_transition",)
