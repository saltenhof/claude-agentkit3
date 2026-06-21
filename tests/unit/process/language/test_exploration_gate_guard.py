"""Defense-in-depth unit tests for the exploration_gate_approved guard (AC4).

FK-23 §23.5.0 / FK-45 §45.2: ``COMPLETED`` is NOT sufficient to enter
implementation — the persisted ``ExplorationPayload.gate_status`` must be
``APPROVED``. Every other combination fails closed.
"""

from __future__ import annotations

from tests.phase_state_factory import make_phase_state

from agentkit.backend.core_types import ExplorationGateStatus
from agentkit.backend.pipeline_engine.phase_executor import (
    ExplorationPayload,
    PhaseState,
    PhaseStatus,
)
from agentkit.backend.process.language.guards import exploration_gate_approved
from agentkit.backend.story_context_manager.models import StoryContext as _StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType


def _ctx() -> _StoryContext:
    return _StoryContext(
        project_key="test-project",
        story_id="AG3-045",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
    )


def _state(
    *,
    status: PhaseStatus,
    payload: ExplorationPayload | None,
    phase: str = "exploration",
) -> PhaseState:
    return make_phase_state(
        story_id="AG3-045", phase=phase, status=status, payload=payload
    )


def test_completed_and_approved_passes() -> None:
    state = _state(
        status=PhaseStatus.COMPLETED,
        payload=ExplorationPayload(gate_status=ExplorationGateStatus.APPROVED),
    )
    assert exploration_gate_approved(_ctx(), state).passed is True


def test_completed_and_pending_fails() -> None:
    state = _state(
        status=PhaseStatus.COMPLETED,
        payload=ExplorationPayload(gate_status=ExplorationGateStatus.PENDING),
    )
    result = exploration_gate_approved(_ctx(), state)
    assert result.passed is False
    assert "pending" in (result.reason or "")


def test_completed_and_rejected_fails() -> None:
    state = _state(
        status=PhaseStatus.COMPLETED,
        payload=ExplorationPayload(gate_status=ExplorationGateStatus.REJECTED),
    )
    assert exploration_gate_approved(_ctx(), state).passed is False


def test_completed_without_payload_fails() -> None:
    state = _state(status=PhaseStatus.COMPLETED, payload=None)
    assert exploration_gate_approved(_ctx(), state).passed is False


def test_not_completed_even_when_approved_fails() -> None:
    state = _state(
        status=PhaseStatus.IN_PROGRESS,
        payload=ExplorationPayload(gate_status=ExplorationGateStatus.APPROVED),
    )
    assert exploration_gate_approved(_ctx(), state).passed is False


def test_wrong_phase_fails() -> None:
    state = _state(
        status=PhaseStatus.COMPLETED,
        payload=None,
        phase="implementation",
    )
    assert exploration_gate_approved(_ctx(), state).passed is False
