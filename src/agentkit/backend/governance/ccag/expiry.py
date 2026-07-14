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

from typing import Protocol

from agentkit.backend.pipeline_engine.phase_executor.models import (
    EscalationReason,
    PhaseName,
    PhaseState,
    PhaseStatus,
)


class PhaseStateEscalationPort(Protocol):
    """Authoritative run-status port for the TTL escalation (FK-39).

    Satisfied by
    :class:`agentkit.backend.state_backend.store.phase_envelope_repository.StateBackendPhaseEnvelopeRepository`.
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


__all__ = [
    "PhaseStateEscalationPort",
    "escalate_run_to_phase_state",
]
