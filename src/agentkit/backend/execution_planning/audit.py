"""BC14 planning audit-event emission (FK-70 §70.10.3, FK-68 §68.2.2).

The domain BC14 audit producer. It emits the eight planning audit events at
the respective planning decisions through the EXISTING generic emitter
infrastructure (``telemetry.EventEmitter`` / ``StateBackendEmitter``) against the
AG3-081-delivered ``EventType`` catalogue values and their mandatory-payload
contracts. AG3-099 does NOT add a second event enum and does NOT extend the
catalogue -- it consumes ``telemetry.events.EventType`` and validates each payload
fail-closed via ``validate_event_payload`` before emitting.

Wiring boundary (AG3-099 vs AG3-100):
    Five of the eight events have their decision site inside AG3-099's scope and
    are wired to the REAL decision points:
        * ``dependency_recorded`` -- ingest of a proposed edge
          (``proposal_ingest.ingest_proposal``).
        * ``rulebook_compiled`` -- official rulebook compile/update
          (``rulebook_compile.update_rulebook_revision``).
        * ``plan_revised`` -- the AG3-099 re-plan trigger: a successful rulebook
          update mandates a re-plan (FK-70 §70.6.2a), wired in
          ``rulebook_compile.update_rulebook_revision``.
        * ``story_ready`` / ``story_blocked`` -- the readiness EVALUATION
          (FK-70 §70.6.1), wired in ``lifecycle.assess_readiness``.
    The remaining THREE events -- ``scheduling_decided``, ``gate_resolved`` and
    ``wave_collapsed`` -- have their decision sites in AG3-100's scope
    (``evaluate_scheduling`` / §70.11; gate resolution; wave lifecycle, §2.2).
    They are intentionally NOT given a fake AG3-099 call site. Instead they are a
    REAL, documented SEAM: each emitter method below is a ready producer that
    AG3-100 will call from its scheduling/gate/wave decision points. This is an
    explicit, reviewer-visible cut, not an omission.

Sources:
- FK-70 §70.10.3 -- eight BC14 planning audit events
- FK-70 §70.6.1/§70.6.2a -- readiness + re-plan decision sites (AG3-099)
- FK-70 §70.6.2/§70.6.4/§70.11 -- scheduling/wave decision sites (AG3-100)
- FK-68 §68.2.2 -- BC14 EventType catalogue values + mandatory payloads (AG3-081)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.telemetry.events import Event, EventType, validate_event_payload

if TYPE_CHECKING:
    from agentkit.backend.telemetry.emitters import EventEmitter

__all__ = ["PlanningAuditEmitter"]

_SOURCE_COMPONENT = "execution_planning"


class PlanningAuditEmitter:
    """Emits the eight BC14 planning audit events (FK-70 §70.10.3).

    Thin domain producer over an injected generic ``EventEmitter``. Each method
    builds the canonical payload, validates it fail-closed against the AG3-081
    mandatory-payload contract, and emits one ``Event`` carrying the matching
    AG3-081 ``EventType`` catalogue value.

    Args:
        emitter: The generic event emitter (e.g. ``StateBackendEmitter`` or
            ``MemoryEmitter``) -- pre-existing infra, not built here.
    """

    def __init__(self, emitter: EventEmitter) -> None:
        self._emitter = emitter

    def _emit(
        self,
        event_type: EventType,
        *,
        story_id: str,
        project_key: str | None,
        run_id: str | None,
        payload: dict[str, object],
    ) -> None:
        validate_event_payload(event_type, payload)
        self._emitter.emit(
            Event(
                story_id=story_id,
                event_type=event_type,
                project_key=project_key,
                run_id=run_id,
                source_component=_SOURCE_COMPONENT,
                payload=payload,
            )
        )

    def dependency_recorded(
        self,
        *,
        story_id: str,
        depends_on_id: str,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Emit ``dependency_recorded`` (a dependency edge entered the graph)."""
        self._emit(
            EventType.DEPENDENCY_RECORDED,
            story_id=story_id,
            project_key=project_key,
            run_id=run_id,
            payload={"story_id": story_id, "depends_on_id": depends_on_id},
        )

    def story_ready(
        self,
        *,
        story_id: str,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Emit ``story_ready`` (a story transitioned to READY)."""
        self._emit(
            EventType.STORY_READY,
            story_id=story_id,
            project_key=project_key,
            run_id=run_id,
            payload={"story_id": story_id},
        )

    def story_blocked(
        self,
        *,
        story_id: str,
        reason: str,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Emit ``story_blocked`` (a story transitioned to BLOCKED)."""
        self._emit(
            EventType.STORY_BLOCKED,
            story_id=story_id,
            project_key=project_key,
            run_id=run_id,
            payload={"story_id": story_id, "reason": reason},
        )

    def plan_revised(
        self,
        *,
        story_id: str,
        plan_id: str,
        trigger: str,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Emit ``plan_revised`` (an execution plan was created or revised)."""
        self._emit(
            EventType.PLAN_REVISED,
            story_id=story_id,
            project_key=project_key,
            run_id=run_id,
            payload={"plan_id": plan_id, "trigger": trigger},
        )

    def scheduling_decided(
        self,
        *,
        story_id: str,
        wave_id: str,
        decision: str,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Emit ``scheduling_decided`` (a scheduling decision was taken).

        AG3-100 SEAM: the scheduling decision site is ``evaluate_scheduling``
        (FK-70 §70.6.2/§70.11), owned by AG3-100. AG3-100 is the wiring owner of
        this call; AG3-099 provides the producer but has no scheduling decision
        site to call it from.
        """
        self._emit(
            EventType.SCHEDULING_DECIDED,
            story_id=story_id,
            project_key=project_key,
            run_id=run_id,
            payload={"story_id": story_id, "wave_id": wave_id, "decision": decision},
        )

    def gate_resolved(
        self,
        *,
        story_id: str,
        gate_id: str,
        result: str,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Emit ``gate_resolved`` (a human/external gate was resolved).

        AG3-100 SEAM: the gate-resolution decision site (§70.5.3 gate lifecycle,
        consumed by the AG3-100 scheduling/admission flow) is owned by AG3-100.
        AG3-100 is the wiring owner of this call; AG3-099 provides the producer.
        """
        self._emit(
            EventType.GATE_RESOLVED,
            story_id=story_id,
            project_key=project_key,
            run_id=run_id,
            payload={"gate_id": gate_id, "result": result},
        )

    def rulebook_compiled(
        self,
        *,
        story_id: str,
        rulebook_id: str,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Emit ``rulebook_compiled`` (a rulebook was compiled or rejected)."""
        self._emit(
            EventType.RULEBOOK_COMPILED,
            story_id=story_id,
            project_key=project_key,
            run_id=run_id,
            payload={"rulebook_id": rulebook_id},
        )

    def wave_collapsed(
        self,
        *,
        story_id: str,
        wave_id: str,
        story_count: int,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Emit ``wave_collapsed`` (a wave collapsed or was re-cut).

        AG3-100 SEAM: the wave-lifecycle decision site (§70.6.4 wave
        planned/active/completed/collapsed, driven by the AG3-100 scheduling
        loop) is owned by AG3-100. AG3-100 is the wiring owner of this call;
        AG3-099 provides the producer (``lifecycle.mark_wave_after_results``
        derives the collapsed lifecycle but the per-run emission is AG3-100's).
        """
        self._emit(
            EventType.WAVE_COLLAPSED,
            story_id=story_id,
            project_key=project_key,
            run_id=run_id,
            payload={"wave_id": wave_id, "story_count": story_count},
        )
