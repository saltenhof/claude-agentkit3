"""Contract: the exploration exit-gate is defense-in-depth (FK-23 §23.5.0).

Pins the invariant that ONLY ``ExplorationGateStatus.APPROVED`` on a
``COMPLETED`` exploration phase releases the implementation phase. Parametrised
over the full ``ExplorationGateStatus`` enum (the SSOT) so a newly added status
value is re-checked automatically and cannot silently become an entry path.
"""

from __future__ import annotations

import pytest

from agentkit.core_types import ExplorationGateStatus
from agentkit.process.language.guards import exploration_gate_approved
from agentkit.story_context_manager.models import (
    ExplorationPayload,
    PhaseState,
    PhaseStatus,
)
from agentkit.story_context_manager.models import StoryContext as _StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType


def _ctx() -> _StoryContext:
    return _StoryContext(
        project_key="test-project",
        story_id="AG3-045",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
    )


@pytest.mark.parametrize("gate_status", list(ExplorationGateStatus))
def test_only_approved_releases_implementation(
    gate_status: ExplorationGateStatus,
) -> None:
    state = PhaseState(
        story_id="AG3-045",
        phase="exploration",
        status=PhaseStatus.COMPLETED,
        payload=ExplorationPayload(gate_status=gate_status),
    )
    expected = gate_status is ExplorationGateStatus.APPROVED
    assert exploration_gate_approved(_ctx(), state).passed is expected


def test_completed_without_payload_is_closed() -> None:
    state = PhaseState(
        story_id="AG3-045",
        phase="exploration",
        status=PhaseStatus.COMPLETED,
        payload=None,
    )
    assert exploration_gate_approved(_ctx(), state).passed is False
