"""Unit tests for new EventTypes + validate_event_payload (AG3-037 §2.1.3/2.1.4)."""

from __future__ import annotations

import pytest

from agentkit.telemetry.events import (
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
    EventType.INTEGRITY_VIOLATION: {"stage": "escape_detection"},
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
    "integrity_gate_result": {"blocked_dimensions": []},
    "are_gate_result": {"covered": 1, "required": 2, "coverage_ratio": 0.5},
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
