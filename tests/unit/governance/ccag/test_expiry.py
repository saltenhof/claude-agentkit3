"""Unit tests for the permission-TTL -> run ESCALATION wiring (AG3-086 AC7).

FK-42 §42.4.2 step 5 / FK-93 §93.5a: a permission request whose TTL elapses
without a human decision deterministically sets the run's authoritative
``PhaseState`` to ``ESCALATED`` (reason ``permission_request_expired``). The TTL
default is the FK-93-conformant 1800s via ``permissions.request_ttl_s``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.phase_state_factory import make_phase_state

from agentkit.backend.config.models import PermissionsConfig
from agentkit.backend.governance.ccag.expiry import (
    PermissionExpiryEscalator,
    escalate_run_to_phase_state,
)
from agentkit.backend.governance.ccag.requests import (
    DEFAULT_TTL_SECONDS,
    PermissionRequestStore,
)
from agentkit.backend.pipeline_engine.phase_executor.models import (
    EscalationReason,
    PhaseName,
    PhaseState,
    PhaseStatus,
)

if TYPE_CHECKING:
    from pathlib import Path


class _InMemoryPhaseStatePort:
    """First-class in-memory ``PhaseStateEscalationPort`` (not a mock)."""

    def __init__(self, state: PhaseState | None) -> None:
        self.state = state

    def load_state(self, story_id: str, phase: PhaseName) -> PhaseState | None:
        _ = story_id, phase
        return self.state

    def save_state(self, state: PhaseState) -> None:
        self.state = state


# ---------------------------------------------------------------------------
# AC7 — config default is the FK-93 1800s (not the hard-coded 600)
# ---------------------------------------------------------------------------


def test_permission_request_ttl_default_is_1800() -> None:
    assert PermissionsConfig().request_ttl_s == 1800


def test_module_default_ttl_seconds_is_1800() -> None:
    # The in-module fallback is raised to the FK-93 Sollwert (was 600).
    assert DEFAULT_TTL_SECONDS == 1800


# ---------------------------------------------------------------------------
# AC7 — expired request -> run ESCALATED (authoritative PhaseState)
# ---------------------------------------------------------------------------


def _make_expired_request(store: PermissionRequestStore, story_id: str) -> None:
    """Create a request whose TTL has already elapsed (expires_at in the past)."""
    store.create(
        request_id="req-1",
        tool_name="Bash",
        story_id=story_id,
        run_id="run-1",
        ttl_seconds=-10,  # expires_at is 10s in the past -> effective_status "expired"
    )


def test_expired_request_escalates_run(tmp_path: Path) -> None:
    store = PermissionRequestStore(tmp_path / "req.db")
    _make_expired_request(store, "AG3-001")
    port = _InMemoryPhaseStatePort(
        make_phase_state(story_id="AG3-001", status=PhaseStatus.IN_PROGRESS)
    )
    escalator = PermissionExpiryEscalator(store, port)

    escalated = escalator.expire_and_escalate("AG3-001")

    assert escalated is True
    assert port.state is not None
    assert port.state.status is PhaseStatus.ESCALATED
    assert port.state.escalation_reason is EscalationReason.PERMISSION_REQUEST_EXPIRED


def test_no_expired_request_does_not_escalate(tmp_path: Path) -> None:
    store = PermissionRequestStore(tmp_path / "req.db")
    store.create(
        request_id="req-fresh",
        tool_name="Bash",
        story_id="AG3-001",
        run_id="run-1",
        ttl_seconds=3600,  # not expired
    )
    port = _InMemoryPhaseStatePort(
        make_phase_state(story_id="AG3-001", status=PhaseStatus.IN_PROGRESS)
    )
    escalator = PermissionExpiryEscalator(store, port)

    escalated = escalator.expire_and_escalate("AG3-001")

    assert escalated is False
    assert port.state is not None
    assert port.state.status is PhaseStatus.IN_PROGRESS


def test_already_escalated_is_idempotent(tmp_path: Path) -> None:
    store = PermissionRequestStore(tmp_path / "req.db")
    _make_expired_request(store, "AG3-001")
    port = _InMemoryPhaseStatePort(
        make_phase_state(
            story_id="AG3-001",
            status=PhaseStatus.ESCALATED,
            escalation_reason=EscalationReason.GOVERNANCE_VIOLATION,
        )
    )
    escalator = PermissionExpiryEscalator(store, port)

    escalated = escalator.expire_and_escalate("AG3-001")

    assert escalated is False  # already ESCALATED -> no transition
    assert port.state is not None
    # The pre-existing escalation reason is preserved (idempotent, no overwrite).
    assert port.state.escalation_reason is EscalationReason.GOVERNANCE_VIOLATION


def test_no_phase_state_cannot_escalate(tmp_path: Path) -> None:
    store = PermissionRequestStore(tmp_path / "req.db")
    _make_expired_request(store, "AG3-001")
    port = _InMemoryPhaseStatePort(None)  # no durable run-status
    escalator = PermissionExpiryEscalator(store, port)

    assert escalator.expire_and_escalate("AG3-001") is False


def test_escalate_helper_clears_pause_reason() -> None:
    # A PAUSED state (with pause_reason) escalates cleanly: pause_reason cleared,
    # escalation_reason set, satisfying the PhaseState consistency invariant.
    from agentkit.backend.core_types import PauseReason

    paused = make_phase_state(
        status=PhaseStatus.PAUSED, pause_reason=PauseReason.GOVERNANCE_INCIDENT
    )
    escalated = escalate_run_to_phase_state(paused)
    assert escalated.status is PhaseStatus.ESCALATED
    assert escalated.pause_reason is None
    assert escalated.escalation_reason is EscalationReason.PERMISSION_REQUEST_EXPIRED
