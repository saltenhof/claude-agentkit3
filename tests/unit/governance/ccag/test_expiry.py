"""Unit tests for permission-expiry run-state escalation."""

from __future__ import annotations

from tests.phase_state_factory import make_phase_state

from agentkit.backend.config.models import PermissionsConfig
from agentkit.backend.core_types import PauseReason
from agentkit.backend.governance.ccag.expiry import escalate_run_to_phase_state
from agentkit.backend.pipeline_engine.phase_executor.models import (
    EscalationReason,
    PhaseStatus,
)


def test_permission_request_ttl_default_is_1800() -> None:
    assert PermissionsConfig().request_ttl_s == 1800


def test_escalate_helper_clears_pause_reason() -> None:
    paused = make_phase_state(
        status=PhaseStatus.PAUSED, pause_reason=PauseReason.GOVERNANCE_INCIDENT
    )
    escalated = escalate_run_to_phase_state(paused)
    assert escalated.status is PhaseStatus.ESCALATED
    assert escalated.pause_reason is None
    assert escalated.escalation_reason is EscalationReason.PERMISSION_REQUEST_EXPIRED
