"""Contract tests for governance-observer EventType mandatory payload fields (AG3-085).

Pins the four FK-91 governance EventTypes and their mandatory payload contracts
per FK-35 §35.3.6 / §35.3.7 / §35.3.8.  Also tests EventType catalog and
validate_event_payload (fail-closed) for each governance event type.
"""

from __future__ import annotations

import pytest

from agentkit.telemetry.events import (
    EventPayloadContractError,
    EventType,
    validate_event_payload,
)

# ---------------------------------------------------------------------------
# EventType catalog presence
# ---------------------------------------------------------------------------

_GOVERNANCE_WIRE_VALUES = {
    "governance_signal",
    "governance_adjudication",
    "governance_incident_opened",
    "governance_measure_applied",
}


def test_all_governance_event_types_in_catalog() -> None:
    """All four FK-91 governance EventTypes must be in the catalog (AC8)."""
    actual = {member.value for member in EventType}
    for wire in _GOVERNANCE_WIRE_VALUES:
        assert wire in actual, f"{wire!r} missing from EventType catalog"


def test_governance_signal_wire_value() -> None:
    """governance_signal wire value is exact (FK-91, AC8)."""
    assert EventType.GOVERNANCE_SIGNAL == "governance_signal"


def test_governance_adjudication_wire_value() -> None:
    """governance_adjudication wire value is exact (FK-91, AC8)."""
    assert EventType.GOVERNANCE_ADJUDICATION == "governance_adjudication"


def test_governance_incident_opened_wire_value() -> None:
    """governance_incident_opened wire value is exact (FK-91, AC8)."""
    assert EventType.GOVERNANCE_INCIDENT_OPENED == "governance_incident_opened"


def test_governance_measure_applied_wire_value() -> None:
    """governance_measure_applied wire value is exact (FK-91, AC8)."""
    assert EventType.GOVERNANCE_MEASURE_APPLIED == "governance_measure_applied"


# ---------------------------------------------------------------------------
# Mandatory payload field validation (fail-closed)
# ---------------------------------------------------------------------------

def test_governance_adjudication_valid_payload_passes() -> None:
    """governance_adjudication with all mandatory fields validates green."""
    validate_event_payload(
        EventType.GOVERNANCE_ADJUDICATION,
        {
            "incident_type": "role_violation",
            "severity": "high",
            "confidence": 0.9,
            "recommended_action": "pause_story",
            "signal_type": "orchestrator_code_read_write",
        },
    )


def test_governance_adjudication_missing_field_fails_closed() -> None:
    """governance_adjudication missing any mandatory field raises (AC8 fail-closed)."""
    with pytest.raises(EventPayloadContractError):
        validate_event_payload(
            EventType.GOVERNANCE_ADJUDICATION,
            {
                "incident_type": "role_violation",
                # missing: severity, confidence, recommended_action, signal_type
            },
        )


def test_governance_incident_opened_valid_payload_passes() -> None:
    """governance_incident_opened with all mandatory fields validates green."""
    validate_event_payload(
        EventType.GOVERNANCE_INCIDENT_OPENED,
        {
            "risk_score": 40,
            "event_count": 5,
            "dominant_signals": ["orchestrator_code_read_write"],
        },
    )


def test_governance_incident_opened_missing_field_fails_closed() -> None:
    """governance_incident_opened missing mandatory field raises (AC8 fail-closed)."""
    with pytest.raises(EventPayloadContractError):
        validate_event_payload(
            EventType.GOVERNANCE_INCIDENT_OPENED,
            {"risk_score": 40},  # missing event_count and dominant_signals
        )


def test_governance_measure_applied_valid_payload_passes() -> None:
    """governance_measure_applied with all mandatory fields validates green."""
    validate_event_payload(
        EventType.GOVERNANCE_MEASURE_APPLIED,
        {"measure": "document_incident", "severity": "medium"},
    )


def test_governance_measure_applied_missing_field_fails_closed() -> None:
    """governance_measure_applied missing mandatory field raises (AC8 fail-closed)."""
    with pytest.raises(EventPayloadContractError):
        validate_event_payload(
            EventType.GOVERNANCE_MEASURE_APPLIED,
            {"measure": "document_incident"},  # missing severity
        )


def test_governance_signal_valid_payload_passes() -> None:
    """governance_signal with all mandatory fields validates green."""
    validate_event_payload(
        EventType.GOVERNANCE_SIGNAL,
        {
            "risk_points": 10,
            "signal_type": "orchestrator_code_read_write",
            "actor": "orchestrator",
        },
    )


def test_governance_signal_missing_field_fails_closed() -> None:
    """governance_signal missing mandatory field raises (AC8 fail-closed)."""
    with pytest.raises(EventPayloadContractError):
        validate_event_payload(
            EventType.GOVERNANCE_SIGNAL,
            {"risk_points": 10},  # missing signal_type and actor
        )
