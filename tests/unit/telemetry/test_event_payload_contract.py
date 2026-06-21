"""Unit tests for new EventTypes + validate_event_payload (AG3-037 §2.1.3/2.1.4)."""

from __future__ import annotations

import pytest

from agentkit.backend.telemetry.events import (
    EventPayloadContractError,
    EventType,
    validate_event_payload,
)

# ---------------------------------------------------------------------------
# New EventType values (AC3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("member", "wire"),
    [
        (EventType.VECTORDB_SEARCH, "vectordb_search"),
        (EventType.COMPACTION_EVENT, "compaction_event"),
        (EventType.MANDATE_CLASSIFICATION, "mandate_classification"),
        (EventType.FINE_DESIGN_DECISION, "fine_design_decision"),
        (EventType.SCOPE_EXPLOSION_CHECK, "scope_explosion_check"),
        (EventType.IMPACT_EXCEEDANCE_CHECK, "impact_exceedance_check"),
        # BC14 Execution-Planning (FK-68 §68.2.2, AG3-081 AC1)
        (EventType.DEPENDENCY_RECORDED, "dependency_recorded"),
        (EventType.STORY_READY, "story_ready"),
        (EventType.STORY_BLOCKED, "story_blocked"),
        (EventType.PLAN_REVISED, "plan_revised"),
        (EventType.SCHEDULING_DECIDED, "scheduling_decided"),
        (EventType.GATE_RESOLVED, "gate_resolved"),
        (EventType.RULEBOOK_COMPILED, "rulebook_compiled"),
        (EventType.WAVE_COLLAPSED, "wave_collapsed"),
        # BC15 ARE / Requirements (FK-68 §68.2.2, AG3-081 AC2)
        (EventType.ARE_REQUIREMENTS_LINKED, "are_requirements_linked"),
        (EventType.ARE_EVIDENCE_SUBMITTED, "are_evidence_submitted"),
        (EventType.ARE_GATE_RESULT, "are_gate_result"),
    ],
)
def test_new_event_type_values(member: EventType, wire: str) -> None:
    assert member.value == wire


def test_impact_violation_and_exceedance_are_distinct() -> None:
    # AC3 / story §2.1.3: IMPACT_VIOLATION_CHECK (FK-33) stays separate from the
    # exploration IMPACT_EXCEEDANCE_CHECK (FK-25).
    assert EventType.IMPACT_VIOLATION_CHECK != EventType.IMPACT_EXCEEDANCE_CHECK
    assert EventType.IMPACT_VIOLATION_CHECK.value == "impact_violation_check"


# ---------------------------------------------------------------------------
# validate_event_payload — present mandatory fields pass (AC4)
# ---------------------------------------------------------------------------


_VALID_PAYLOADS: dict[EventType | str, dict[str, object]] = {
    # AG3-086: ``guard``/``detail`` mandatory for every ``integrity_violation``;
    # ``stage`` is conditional (prompt_integrity_guard only). A non-prompt guard
    # validates WITHOUT a ``stage`` (FK-68 §68.2 / FK-61 §61.12.2).
    EventType.INTEGRITY_VIOLATION: {
        "guard": "skill_usage_check",
        "detail": "blocked: use the matching skill",
    },
    EventType.REVIEW_RESPONSE: {"verdict": "PASS"},
    EventType.REVIEW_DIVERGENCE: {
        "story_id": "AG3-001",
        "reviewer_a": "qa",
        "reviewer_b": "security",
        "divergent": True,
        "quorum_triggered": True,
        "final_verdict": "FAIL",
    },
    EventType.VECTORDB_SEARCH: {
        "total_hits": 3,
        "hits_above_threshold": 1,
        "hits_classified_conflict": 0,
        "threshold_value": 0.8,
    },
    EventType.COMPACTION_EVENT: {"story_id": "AG3-001"},
    EventType.IMPACT_VIOLATION_CHECK: {
        "declared_impact": "Local",
        "actual_impact": "Component",
        "result": "violation",
    },
    EventType.DOC_FIDELITY_CHECK: {"level": "goal_fidelity", "result": "pass"},
    EventType.MANDATE_CLASSIFICATION: {
        "escalation_class": "2",
        "decision_summary": "fine design",
        "story_id": "AG3-001",
        "run_id": "run-1",
    },
    EventType.FINE_DESIGN_DECISION: {
        "decision_id": "d1",
        "question": "q",
        "decision": "yes",
        "llm_responses": [],
        "normative_basis": "FK-25",
        "story_id": "AG3-001",
    },
    EventType.SCOPE_EXPLOSION_CHECK: {
        "status": "PASS",
        "indicators": [],
        "story_id": "AG3-001",
    },
    EventType.IMPACT_EXCEEDANCE_CHECK: {
        "declared": "Local",
        "actual": "Local",
        "exceeded": False,
        "story_id": "AG3-001",
    },
    # BC14 Execution-Planning (FK-68 §68.2.2, AG3-081 AC1)
    EventType.DEPENDENCY_RECORDED: {"story_id": "AG3-001", "depends_on_id": "AG3-000"},
    EventType.STORY_READY: {"story_id": "AG3-001"},
    EventType.STORY_BLOCKED: {"story_id": "AG3-001", "reason": "dependency"},
    EventType.PLAN_REVISED: {"plan_id": "p1", "trigger": "scope_change"},
    EventType.SCHEDULING_DECIDED: {
        "story_id": "AG3-001",
        "wave_id": "w1",
        "decision": "scheduled",
    },
    EventType.GATE_RESOLVED: {"gate_id": "g1", "result": "pass"},
    EventType.RULEBOOK_COMPILED: {"rulebook_id": "rb1"},
    EventType.WAVE_COLLAPSED: {"wave_id": "w1", "story_count": 3},
    # BC15 ARE / Requirements (FK-68 §68.2.2, AG3-081 AC2)
    EventType.ARE_REQUIREMENTS_LINKED: {"story_id": "AG3-001", "requirement_count": 4},
    EventType.ARE_EVIDENCE_SUBMITTED: {"story_id": "AG3-001", "evidence_type": "test"},
    # §2.1.3 conflict resolution: mandatory = story_id, result (FK-68 canonical).
    EventType.ARE_GATE_RESULT: {"story_id": "AG3-001", "result": "pass"},
    "integrity_gate_result": {"blocked_dimensions": []},
}


@pytest.mark.parametrize("event_type", list(_VALID_PAYLOADS))
def test_valid_payload_passes(event_type: EventType | str) -> None:
    validate_event_payload(event_type, _VALID_PAYLOADS[event_type])


@pytest.mark.parametrize("event_type", list(_VALID_PAYLOADS))
def test_missing_mandatory_field_raises(event_type: EventType | str) -> None:
    # Drop the first mandatory field -> FAIL-CLOSED (AC4).
    full = dict(_VALID_PAYLOADS[event_type])
    dropped_key = next(iter(full))
    del full[dropped_key]
    with pytest.raises(EventPayloadContractError) as exc:
        validate_event_payload(event_type, full)
    assert dropped_key in exc.value.missing


def test_event_without_mandatory_fields_is_noop() -> None:
    # agent_start carries no mandatory event-specific fields.
    validate_event_payload(EventType.AGENT_START, {})


def test_empty_payload_for_required_event_raises() -> None:
    with pytest.raises(EventPayloadContractError):
        validate_event_payload(EventType.INTEGRITY_VIOLATION, {})


def test_review_divergence_missing_final_verdict_raises() -> None:
    payload = dict(_VALID_PAYLOADS[EventType.REVIEW_DIVERGENCE])
    del payload["final_verdict"]
    with pytest.raises(EventPayloadContractError) as exc:
        validate_event_payload(EventType.REVIEW_DIVERGENCE, payload)
    assert exc.value.missing == ("final_verdict",)


# ---------------------------------------------------------------------------
# BC14 Execution-Planning per-event mandatory contract (AC1)
# ---------------------------------------------------------------------------

_BC14_EVENTS: tuple[EventType, ...] = (
    EventType.DEPENDENCY_RECORDED,
    EventType.STORY_READY,
    EventType.STORY_BLOCKED,
    EventType.PLAN_REVISED,
    EventType.SCHEDULING_DECIDED,
    EventType.GATE_RESOLVED,
    EventType.RULEBOOK_COMPILED,
    EventType.WAVE_COLLAPSED,
)

_BC15_EVENTS: tuple[EventType, ...] = (
    EventType.ARE_REQUIREMENTS_LINKED,
    EventType.ARE_EVIDENCE_SUBMITTED,
    EventType.ARE_GATE_RESULT,
)


@pytest.mark.parametrize("event_type", _BC14_EVENTS)
def test_bc14_event_missing_first_mandatory_field_raises(event_type: EventType) -> None:
    # AC1: each BC14 event rejects a payload missing a mandatory field
    # fail-closed (EventPayloadContractError).
    full = dict(_VALID_PAYLOADS[event_type])
    dropped = next(iter(full))
    del full[dropped]
    with pytest.raises(EventPayloadContractError) as exc:
        validate_event_payload(event_type, full)
    assert dropped in exc.value.missing


@pytest.mark.parametrize("event_type", _BC15_EVENTS)
def test_bc15_event_missing_first_mandatory_field_raises(event_type: EventType) -> None:
    # AC2: each BC15 event rejects a payload missing a mandatory field fail-closed.
    full = dict(_VALID_PAYLOADS[event_type])
    dropped = next(iter(full))
    del full[dropped]
    with pytest.raises(EventPayloadContractError) as exc:
        validate_event_payload(event_type, full)
    assert dropped in exc.value.missing


def test_bc15_events_are_enum_members() -> None:
    # AC2: are_requirements_linked / are_evidence_submitted are full enum members
    # and are_gate_result is a full member (no longer payload-pinning only).
    values = {member.value for member in EventType}
    assert "are_requirements_linked" in values
    assert "are_evidence_submitted" in values
    assert "are_gate_result" in values
    # The wire string resolves to the enum member (full membership, not by-name).
    assert EventType("are_gate_result") is EventType.ARE_GATE_RESULT


def test_are_gate_result_conflict_resolved_one_mandatory_set() -> None:
    # AC2 / §2.1.3: are_gate_result has EXACTLY ONE mandatory set: FK-68's
    # story_id + result. The FK-61 metric fields covered/required/coverage_ratio
    # stay OPTIONAL (enriched) — present-without-mandatory must still fail closed,
    # and mandatory-without-metrics must pass.
    from agentkit.backend.telemetry.events import (
        MANDATORY_PAYLOAD_FIELDS,
        MANDATORY_PAYLOAD_FIELDS_BY_NAME,
    )

    assert MANDATORY_PAYLOAD_FIELDS[EventType.ARE_GATE_RESULT] == ("story_id", "result")
    # No second String-Map path: are_gate_result must NOT live in the by-name map.
    assert "are_gate_result" not in MANDATORY_PAYLOAD_FIELDS_BY_NAME

    # Mandatory present, metrics absent -> PASS (metrics are optional/enriched).
    validate_event_payload(
        EventType.ARE_GATE_RESULT, {"story_id": "AG3-001", "result": "pass"}
    )
    # Metrics present without mandatory result -> FAIL-CLOSED (metrics are not a
    # substitute for the mandatory FK-68 fields).
    with pytest.raises(EventPayloadContractError) as exc:
        validate_event_payload(
            EventType.ARE_GATE_RESULT,
            {"story_id": "AG3-001", "covered": 1, "required": 2, "coverage_ratio": 0.5},
        )
    assert "result" in exc.value.missing
    # Mandatory present WITH enriched optional metrics -> still PASS.
    validate_event_payload(
        EventType.ARE_GATE_RESULT,
        {
            "story_id": "AG3-001",
            "result": "pass",
            "covered": 1,
            "required": 2,
            "coverage_ratio": 0.5,
        },
    )
