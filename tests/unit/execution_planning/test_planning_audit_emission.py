"""BC14 planning audit-event emission tests (AC7).

AC7: the eight BC14 audit events are emitted at the respective planning decisions
through the EXISTING generic emitter infra (``telemetry.emitters.EventEmitter`` /
``MemoryEmitter``) against the AG3-081-delivered ``EventType`` catalogue values;
AG3-099 adds no second enum and validates each payload against the AG3-081
mandatory-payload contract.
"""

from __future__ import annotations

import pytest

from agentkit.execution_planning.audit import PlanningAuditEmitter
from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventPayloadContractError, EventType

_BC14_EVENT_TYPES = {
    EventType.DEPENDENCY_RECORDED,
    EventType.STORY_READY,
    EventType.STORY_BLOCKED,
    EventType.PLAN_REVISED,
    EventType.SCHEDULING_DECIDED,
    EventType.GATE_RESOLVED,
    EventType.RULEBOOK_COMPILED,
    EventType.WAVE_COLLAPSED,
}


def test_all_eight_bc14_events_emitted_against_ag3081_catalog() -> None:
    """All eight BC14 audit events emit against the AG3-081 EventType values."""
    emitter = MemoryEmitter()
    audit = PlanningAuditEmitter(emitter)

    audit.dependency_recorded(story_id="S1", depends_on_id="S0", project_key="P")
    audit.story_ready(story_id="S1", project_key="P")
    audit.story_blocked(story_id="S1", reason="blocked_external", project_key="P")
    audit.plan_revised(story_id="S1", plan_id="PLAN-1", trigger="story_done", project_key="P")
    audit.scheduling_decided(
        story_id="S1", wave_id="W1", decision="parallelize", project_key="P"
    )
    audit.gate_resolved(story_id="S1", gate_id="G1", result="resolved", project_key="P")
    audit.rulebook_compiled(story_id="S1", rulebook_id="RB-1", project_key="P")
    audit.wave_collapsed(story_id="S1", wave_id="W1", story_count=3, project_key="P")

    emitted = {event.event_type for event in emitter.all_events}
    assert emitted == _BC14_EVENT_TYPES
    assert len(emitter.all_events) == 8


def test_emitted_events_use_planning_source_component() -> None:
    """Emitted events carry the execution-planning source component (BC14 owner)."""
    emitter = MemoryEmitter()
    PlanningAuditEmitter(emitter).story_ready(story_id="S1", project_key="P")
    assert emitter.all_events[0].source_component == "execution_planning"


def test_mandatory_payload_contract_enforced_fail_closed() -> None:
    """A planning event with a missing mandatory field fails closed.

    ``story_blocked`` requires ``reason`` (FK-68 §68.2.2). The emitter validates
    via ``validate_event_payload`` before emitting; a direct under-specified call
    raises ``EventPayloadContractError`` rather than persisting a bad event.
    """
    emitter = MemoryEmitter()
    audit = PlanningAuditEmitter(emitter)
    with pytest.raises(EventPayloadContractError):
        # Bypass the typed helper to prove the validation gate is wired.
        audit._emit(  # noqa: SLF001
            EventType.STORY_BLOCKED,
            story_id="S1",
            project_key="P",
            run_id=None,
            payload={"story_id": "S1"},  # missing mandatory "reason"
        )
    assert emitter.all_events == []
