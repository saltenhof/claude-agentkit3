"""Mandatory adversarial sparring over the AG3-065 transport (FK-48 §48.1.6 / FK-11 §11.8).

AG3-079 AC3: the Layer-3 runtime MUST force at least one sparring call over the
configured ``adversarial_sparring`` pool (``{adversarial_sparring}_acquire ->
send -> release``) and emit TWO telemetry facts:

* :data:`~agentkit.telemetry.events.EventType.LLM_CALL` with
  ``role=adversarial_sparring`` (the pool-send fact, FK-11 §11.8.2), and
* :data:`~agentkit.telemetry.events.EventType.ADVERSARIAL_SPARRING` with a
  ``pool`` field (the adversarial domain event, FK-48 §48.1.6).

This module consumes the AG3-065 verify-LLM-transport (the narrow
:class:`~agentkit.verify_system.llm_evaluator.llm_client.LlmClient` port — its
``complete(role, prompt)`` orchestrates acquire/send/release internally). It does
NOT build a second pool adapter and NO fallback (FK-48 §48.1.6, story §2.2): a
transport failure is fail-closed (the sparring did not happen -> Layer 3 FAILs).
The LLM/worker boundary is the only allowed mock boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.telemetry.events import Event, EventType, validate_event_payload
from agentkit.verify_system.adversarial_orchestrator.runtime.models import SparringProof

if TYPE_CHECKING:
    from agentkit.telemetry.emitters import EventEmitter
    from agentkit.verify_system.llm_evaluator.llm_client import (
        LlmClient,
        RolePoolResolver,
    )

#: The configured sparring reviewer role (FK-11 §11.3.1 ``llm_roles``).
ADVERSARIAL_SPARRING_ROLE: str = "adversarial_sparring"

#: Telemetry payload key carrying the role (FK-11 §11.8.2 ``llm_call`` role).
_ROLE_KEY: str = "role"

#: Telemetry payload key carrying the sparring pool (FK-48 §48.1.6 ``pool``).
_POOL_KEY: str = "pool"


class AdversarialSparringError(Exception):
    """Raised when the mandatory sparring call fails (fail-closed, FK-48 §48.1.6).

    A missing/failed sparring call means the Layer-3 mandatory-sparring duty was
    not fulfilled. The runtime turns this into a Layer-3 FAIL (no PASS without a
    proven sparring call) instead of silently skipping it (NO ERROR BYPASSING).
    """


def run_mandatory_sparring(
    *,
    sparring_client: LlmClient,
    emitter: EventEmitter,
    story_id: str,
    run_id: str,
    prompt: str,
    resolver: RolePoolResolver | None = None,
    phase: str | None = None,
) -> SparringProof:
    """Force the mandatory sparring call and emit the two telemetry facts.

    Drives the AG3-065 transport once (``complete(role="adversarial_sparring",
    prompt=...)`` => acquire/send/release) and, on success, emits both the
    FK-11 §11.8.2 ``llm_call`` fact (with ``role=adversarial_sparring``) and the
    FK-48 §48.1.6 ``adversarial_sparring`` domain event (with the ``pool``
    field). The emitted-event counts are recorded in the returned
    :class:`SparringProof` so they can be mirrored into ``adversarial.json`` (the
    single source of truth the integrity gate verifies).

    Args:
        sparring_client: The AG3-065 verify-LLM-transport (consumed, not rebuilt).
        emitter: The telemetry emitter to write the two facts to.
        story_id: Story display id for the events.
        run_id: Run-correlation id for the events.
        prompt: The sparring prompt (FK-48 §48.1.3 phase 3 "what did I miss?").
        resolver: Optional role->pool resolver to record the concrete pool name
            in the ``pool`` field. When ``None`` the role wire-string is used as
            the pool label (the call still happens; the transport resolves the
            pool internally).
        phase: Optional pipeline phase name stamped on the events.

    Returns:
        A :class:`SparringProof` with the pool and the emitted-event counts.

    Raises:
        AdversarialSparringError: When the transport call fails (fail-closed).
    """
    from agentkit.verify_system.llm_evaluator.llm_client import LlmClientError

    # NO FALLBACK (story §2.2 / AC3): pool resolution is part of the mandatory
    # sparring transport. A resolver failure means the sparring pool could not be
    # bound -> fail-closed (Layer-3 FAIL), never substitute a default pool label.
    try:
        pool = _resolve_pool_label(resolver)
    except LlmClientError as exc:
        raise AdversarialSparringError(
            "Mandatory adversarial sparring pool could not be resolved over the "
            f"verify-LLM transport (role={ADVERSARIAL_SPARRING_ROLE!r}): "
            f"{type(exc).__name__}: {exc}. FAIL-CLOSED: an unresolvable sparring "
            "pool is a Layer-3 FAIL, never a fallback to a default pool label "
            "(FK-48 §48.1.6, story §2.2 NO FALLBACK)."
        ) from exc
    try:
        response = sparring_client.complete(
            role=ADVERSARIAL_SPARRING_ROLE, prompt=prompt
        )
    except LlmClientError as exc:
        raise AdversarialSparringError(
            "Mandatory adversarial sparring call failed over the verify-LLM "
            f"transport (role={ADVERSARIAL_SPARRING_ROLE!r}, pool={pool!r}): "
            f"{type(exc).__name__}: {exc}. FAIL-CLOSED: a missing sparring call "
            "is a Layer-3 FAIL, never a silent skip (FK-48 §48.1.6)."
        ) from exc

    edge_cases = _count_edge_cases(response)
    # FK-11 §11.8.2: the pool-send fact, role=adversarial_sparring.
    _emit_llm_call(emitter, story_id=story_id, run_id=run_id, pool=pool, phase=phase)
    # FK-48 §48.1.6: the adversarial domain event with the pool field.
    _emit_adversarial_sparring(
        emitter, story_id=story_id, run_id=run_id, pool=pool, phase=phase
    )
    return SparringProof(
        pool=pool,
        adversarial_sparring_events=1,
        llm_call_sparring_events=1,
        edge_cases_received=edge_cases,
        edge_cases_implemented=0,
    )


def _resolve_pool_label(resolver: RolePoolResolver | None) -> str:
    """Resolve the concrete sparring pool label (NO fallback, fail-closed).

    When a resolver is wired, an :class:`LlmClientError` during resolution is
    propagated (NOT swallowed): the caller turns it into a Layer-3 FAIL. There
    is NO fallback to the role wire-string on a transport/pool-resolution
    failure (story §2.2 / AC3: NO FALLBACK for the AG3-065 sparring transport).

    When NO resolver is wired the role wire-string is used as the pool label —
    this is not a fallback but the documented no-resolver default (the transport
    still resolves/uses the pool internally; the label is purely the recorded
    pool name in that configuration).

    Args:
        resolver: Optional role->pool resolver.

    Returns:
        The concrete sparring pool label.

    Raises:
        LlmClientError: When a wired resolver cannot resolve the role
            (propagated; the caller fails closed).
    """
    if resolver is None:
        return ADVERSARIAL_SPARRING_ROLE
    return str(resolver.resolve(ADVERSARIAL_SPARRING_ROLE))


def _count_edge_cases(response: str) -> int:
    """Count edge-case ideas in the sparring response (best-effort line count)."""
    return sum(1 for line in response.splitlines() if line.strip())


def _emit_llm_call(
    emitter: EventEmitter,
    *,
    story_id: str,
    run_id: str,
    pool: str,
    phase: str | None,
) -> None:
    """Emit the FK-11 §11.8.2 ``llm_call`` fact (role=adversarial_sparring)."""
    payload: dict[str, object] = {
        _ROLE_KEY: ADVERSARIAL_SPARRING_ROLE,
        _POOL_KEY: pool,
    }
    validate_event_payload(EventType.LLM_CALL, payload)
    emitter.emit(
        Event(
            story_id=story_id,
            event_type=EventType.LLM_CALL,
            source_component="adversarial_runtime",
            phase=phase,
            payload=payload,
            run_id=run_id,
        )
    )


def _emit_adversarial_sparring(
    emitter: EventEmitter,
    *,
    story_id: str,
    run_id: str,
    pool: str,
    phase: str | None,
) -> None:
    """Emit the FK-48 §48.1.6 ``adversarial_sparring`` domain event (pool field)."""
    payload: dict[str, object] = {_POOL_KEY: pool, _ROLE_KEY: ADVERSARIAL_SPARRING_ROLE}
    validate_event_payload(EventType.ADVERSARIAL_SPARRING, payload)
    emitter.emit(
        Event(
            story_id=story_id,
            event_type=EventType.ADVERSARIAL_SPARRING,
            source_component="adversarial_runtime",
            phase=phase,
            payload=payload,
            run_id=run_id,
        )
    )


__all__ = [
    "ADVERSARIAL_SPARRING_ROLE",
    "AdversarialSparringError",
    "run_mandatory_sparring",
]
