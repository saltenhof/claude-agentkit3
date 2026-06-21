"""Mandate-classification telemetry emission (FK-25 §25.8).

FK-25 §25.8 pins four telemetry events for the exploration mandate flow. Their
MANDATORY payload fields are the authoritative contract pinned by AG3-037 in
``agentkit.backend.telemetry.events.MANDATORY_PAYLOAD_FIELDS`` (validated fail-closed by
``validate_event_payload``); this module emits EXACTLY those fields:

============================  ==========================================
EventType                     mandatory payload fields (AG3-037)
============================  ==========================================
``MANDATE_CLASSIFICATION``    escalation_class, decision_summary,
                              story_id, run_id
``SCOPE_EXPLOSION_CHECK``     status, indicators, story_id
``IMPACT_EXCEEDANCE_CHECK``   declared, actual, exceeded, story_id
``FINE_DESIGN_DECISION``      decision_id, question, decision,
                              llm_responses, normative_basis, story_id
============================  ==========================================

Emission goes through an injected :class:`~agentkit.backend.telemetry.emitters.EventEmitter`
port (wired to ``StateBackendEmitter`` at the composition-root); the bloodgroup-A
core never persists telemetry itself. ``validate_event_payload`` is called before
each emit (fail-closed: a missing mandatory field raises rather than persisting
an under-specified event).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.telemetry.events import Event, EventType, validate_event_payload

if TYPE_CHECKING:
    from agentkit.backend.exploration.mandate.classification import (
        MandateClassificationResult,
    )
    from agentkit.backend.exploration.mandate.fine_design import FineDesignDecision
    from agentkit.backend.telemetry.emitters import EventEmitter

#: The telemetry phase label for the exploration mandate events.
_PHASE = "exploration"
#: The telemetry source component for the exploration mandate events.
_SOURCE = "exploration-mandate"


class MandateTelemetry:
    """Emit the four FK-25 §25.8 mandate telemetry events (fail-closed)."""

    def __init__(self, emitter: EventEmitter) -> None:
        """Initialise the emitter wrapper.

        Args:
            emitter: The injected canonical telemetry emitter port (wired to
                ``StateBackendEmitter`` at the composition-root).
        """
        self._emitter = emitter

    def emit_classification(
        self,
        result: MandateClassificationResult,
        *,
        story_id: str,
        run_id: str,
    ) -> None:
        """Emit ``mandate_classification`` AND its two sub-check events.

        FK-25 §25.8: the scope-explosion and impact-exceedance checks emit their
        own events (always, since both checks always run); the overall classifier
        emits ``mandate_classification`` with the winning class.

        Args:
            result: The classification result (carries both sub-results).
            story_id: The story display id.
            run_id: The run correlation id.
        """
        self.emit_scope_explosion(result, story_id=story_id)
        self.emit_impact_exceedance(result, story_id=story_id)
        payload: dict[str, object] = {
            "escalation_class": result.mandate_class.value,
            "decision_summary": result.decision_summary,
            "story_id": story_id,
            "run_id": run_id,
        }
        self._emit(EventType.MANDATE_CLASSIFICATION, story_id, run_id, payload)

    def emit_scope_explosion(
        self, result: MandateClassificationResult, *, story_id: str
    ) -> None:
        """Emit ``scope_explosion_check`` (FK-25 §25.8 / §25.6).

        Args:
            result: The classification result (carries the scope sub-result).
            story_id: The story display id.
        """
        scope = result.scope_explosion
        payload: dict[str, object] = {
            "status": "exploded" if scope.triggered else "pass",
            "indicators": [ind.model_dump(mode="json") for ind in scope.indicators],
            "story_id": story_id,
        }
        self._emit(EventType.SCOPE_EXPLOSION_CHECK, story_id, None, payload)

    def emit_impact_exceedance(
        self, result: MandateClassificationResult, *, story_id: str
    ) -> None:
        """Emit ``impact_exceedance_check`` (FK-25 §25.8 / §25.7).

        Args:
            result: The classification result (carries the impact sub-result).
            story_id: The story display id.
        """
        impact = result.impact_exceedance
        payload: dict[str, object] = {
            "declared": impact.declared.value,
            "actual": impact.actual.value,
            "exceeded": impact.exceeded,
            "story_id": story_id,
        }
        self._emit(EventType.IMPACT_EXCEEDANCE_CHECK, story_id, None, payload)

    def emit_fine_design_decision(
        self,
        decision: FineDesignDecision,
        *,
        story_id: str,
        run_id: str,
    ) -> None:
        """Emit one ``fine_design_decision`` event (FK-25 §25.8 / §25.5).

        Args:
            decision: The documented fine-design decision.
            story_id: The story display id.
            run_id: The run correlation id.
        """
        payload: dict[str, object] = {
            "decision_id": decision.decision_id,
            "question": decision.question,
            "decision": decision.decision,
            "llm_responses": list(decision.llm_responses),
            "normative_basis": list(decision.normative_basis),
            "story_id": story_id,
        }
        self._emit(EventType.FINE_DESIGN_DECISION, story_id, run_id, payload)

    def _emit(
        self,
        event_type: EventType,
        story_id: str,
        run_id: str | None,
        payload: dict[str, object],
    ) -> None:
        """Validate (fail-closed) then emit one event through the injected port.

        Args:
            event_type: The event type.
            story_id: The story display id.
            run_id: The run correlation id, or ``None`` for events that do not
                pin it (scope / impact checks).
            payload: The event payload (must carry the mandatory fields).

        Raises:
            EventPayloadContractError: If a mandatory payload field is missing
                (fail-closed; never persists an under-specified event).
        """
        validate_event_payload(event_type, payload)
        self._emitter.emit(
            Event(
                story_id=story_id,
                event_type=event_type,
                phase=_PHASE,
                source_component=_SOURCE,
                payload=payload,
                run_id=run_id,
            )
        )


__all__ = ["MandateTelemetry"]
