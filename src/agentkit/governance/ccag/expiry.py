"""Permission-request TTL expiry -> deterministic run ESCALATION (FK-42 §42.4.2).

FK-42 §42.4.2 step 5 / FK-55 §55.9a / §55.10.9a: a CCAG ``permission_request``
that elapses without a human decision does NOT hang the run forever — the run is
deterministically set to ``ESCALATED``. Expiry is materialised LAZILY at the next
relevant hook / CLI access (FK-55 §55.10.9a: "not enforced by a permanent
daemon, but lazily").

This module wires the expiry to the AUTHORITATIVE run-status source (the durable
``PhaseState.status`` owned by the phase executor, FK-39) — NOT a shadow field.
The transition is idempotent: an already-ESCALATED state is left unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from agentkit.pipeline_engine.phase_executor.models import (
    EscalationReason,
    PhaseName,
    PhaseState,
    PhaseStatus,
)

if TYPE_CHECKING:
    from agentkit.governance.ccag.requests import PermissionRequestStore


class PhaseStateEscalationPort(Protocol):
    """Authoritative run-status port for the TTL escalation (FK-39).

    Satisfied by
    :class:`agentkit.state_backend.store.phase_envelope_repository.StateBackendPhaseEnvelopeRepository`.
    The escalator never writes a shadow status field; it reads and re-persists the
    durable ``PhaseState`` (the single run-status truth).
    """

    def load_state(self, story_id: str, phase: PhaseName) -> PhaseState | None:
        """Load the current ``PhaseState`` for ``(story_id, phase)``."""
        ...

    def save_state(self, state: PhaseState) -> None:
        """Persist the ``PhaseState`` (the authoritative run-status write)."""
        ...


def escalate_run_to_phase_state(state: PhaseState) -> PhaseState:
    """Return ``state`` transitioned to ESCALATED for a permission-TTL expiry.

    FK-42 §42.4.2 step 5: the run becomes deterministically ``ESCALATED`` with
    reason ``permission_request_expired``. The ``pause_reason`` is cleared (it is
    only valid while PAUSED) so the resulting state satisfies the PhaseState
    consistency invariant (``escalation_reason`` only set when ESCALATED). An
    already-ESCALATED state is returned unchanged (idempotent).

    Args:
        state: The current durable phase state.

    Returns:
        The ESCALATED phase state (or ``state`` unchanged if already ESCALATED).
    """
    if state.status is PhaseStatus.ESCALATED:
        return state
    return state.model_copy(
        update={
            "status": PhaseStatus.ESCALATED,
            "escalation_reason": EscalationReason.PERMISSION_REQUEST_EXPIRED,
            "pause_reason": None,
        }
    )


class PermissionExpiryEscalator:
    """Lazily expires permission requests and escalates the run (FK-42 §42.4.2).

    Args:
        request_store: The CCAG permission-request store (TTL source of truth).
        phase_state_port: The authoritative run-status port (durable PhaseState).
    """

    def __init__(
        self,
        request_store: PermissionRequestStore,
        phase_state_port: PhaseStateEscalationPort,
    ) -> None:
        self._request_store = request_store
        self._phase_state_port = phase_state_port

    def expire_and_escalate(self, story_id: str) -> bool:
        """Expire any TTL-elapsed pending request for ``story_id`` and escalate.

        FK-55 §55.10.9a (lazy materialisation): inspects the pending requests for
        ``story_id`` and, when at least one has TTL-elapsed
        (``effective_status() == "expired"``), sets the run's authoritative
        ``PhaseState`` to ``ESCALATED`` (reason ``permission_request_expired``).
        Idempotent: no expired request -> no change; an already-ESCALATED state is
        left unchanged.

        Args:
            story_id: The story whose pending permission requests are inspected.

        Returns:
            ``True`` when the run was escalated (an expired request drove an
            ESCALATED transition), ``False`` otherwise.
        """
        pending = self._request_store.list_pending(story_id=story_id)
        has_expired = any(req.effective_status() == "expired" for req in pending)
        if not has_expired:
            return False

        # Load the authoritative run-status (the durable PhaseState). The
        # phase argument is protocol-compatible; the store keys on the story dir.
        state = self._phase_state_port.load_state(story_id, PhaseName.IMPLEMENTATION)
        if state is None:
            # No durable run-status to escalate (no active phase state). The
            # expiry is still recorded against the request below; without a
            # PhaseState there is no run to set ESCALATED.
            return False
        escalated = escalate_run_to_phase_state(state)
        if escalated is state:
            return False  # already ESCALATED (idempotent)
        self._phase_state_port.save_state(escalated)
        return True


__all__ = [
    "PermissionExpiryEscalator",
    "PhaseStateEscalationPort",
    "escalate_run_to_phase_state",
]
