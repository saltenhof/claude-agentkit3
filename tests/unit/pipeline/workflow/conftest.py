"""Shared fixtures for workflow DSL unit tests."""

from __future__ import annotations

import pytest

from agentkit.pipeline.workflow.gates import Gate, GateStage
from agentkit.pipeline.workflow.guards import GuardResult
from agentkit.pipeline.workflow.model import (
    HookPoints,
    PhaseDefinition,
    Precondition,
    TransitionRule,
    WorkflowDefinition,
)
from agentkit.story.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story.types import StoryMode, StoryType

if False:  # TYPE_CHECKING — avoid import for type checkers only
    pass


@pytest.fixture()
def minimal_story_context() -> StoryContext:
    """A minimal StoryContext for use in guard tests."""
    return StoryContext(
        story_id="TEST-001",
        story_type=StoryType.IMPLEMENTATION,
        mode=StoryMode.EXPLORATION,
    )


@pytest.fixture()
def execution_story_context() -> StoryContext:
    """A StoryContext with EXECUTION mode."""
    return StoryContext(
        story_id="TEST-002",
        story_type=StoryType.BUGFIX,
        mode=StoryMode.EXECUTION,
    )


@pytest.fixture()
def minimal_phase_state() -> PhaseState:
    """A minimal PhaseState in setup/PENDING."""
    return PhaseState(
        story_id="TEST-001",
        phase="setup",
        status=PhaseStatus.PENDING,
    )


@pytest.fixture()
def completed_setup_state() -> PhaseState:
    """A PhaseState where setup is COMPLETED."""
    return PhaseState(
        story_id="TEST-001",
        phase="setup",
        status=PhaseStatus.COMPLETED,
    )


@pytest.fixture()
def completed_exploration_state() -> PhaseState:
    """A PhaseState where exploration is COMPLETED."""
    return PhaseState(
        story_id="TEST-001",
        phase="exploration",
        status=PhaseStatus.COMPLETED,
    )


@pytest.fixture()
def completed_verify_state() -> PhaseState:
    """A PhaseState where verify is COMPLETED."""
    return PhaseState(
        story_id="TEST-001",
        phase="verify",
        status=PhaseStatus.COMPLETED,
    )


def _always_pass(ctx: StoryContext, state: PhaseState) -> GuardResult:
    """Trivial guard that always passes."""
    return GuardResult.PASS()


def _always_fail(ctx: StoryContext, state: PhaseState) -> GuardResult:
    """Trivial guard that always fails."""
    return GuardResult.FAIL(reason="always fails")


@pytest.fixture()
def minimal_workflow() -> WorkflowDefinition:
    """A minimal two-phase workflow for structural tests."""
    return WorkflowDefinition(
        name="minimal",
        phases=(
            PhaseDefinition(name="start"),
            PhaseDefinition(name="end"),
        ),
        transitions=(
            TransitionRule(source="start", target="end"),
        ),
        hooks=HookPoints(),
    )


@pytest.fixture()
def three_phase_workflow() -> WorkflowDefinition:
    """A three-phase workflow with guards and gates."""
    gate_stage = GateStage(name="check", actor="system")
    gate = Gate(id="test_gate", stages=(gate_stage,))
    return WorkflowDefinition(
        name="three_phase",
        phases=(
            PhaseDefinition(name="alpha"),
            PhaseDefinition(
                name="beta",
                guards=(_always_pass,),
                gates=(gate,),
            ),
            PhaseDefinition(
                name="gamma",
                preconditions=(
                    Precondition(guard=_always_pass),
                ),
            ),
        ),
        transitions=(
            TransitionRule(source="alpha", target="beta", guard=_always_pass),
            TransitionRule(source="beta", target="gamma"),
        ),
        hooks=HookPoints(
            pre_transition=("log_transition",),
            post_transition=("emit_telemetry",),
        ),
    )
