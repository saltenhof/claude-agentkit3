"""Unit tests for the preflight-stream sentinel (FK-68 §68.9.3 / §68.10.2)."""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.telemetry.contract.preflight_sentinel import (
    PREFLIGHT_BALANCE_RULE_ID,
    PREFLIGHT_MISSING,
    PREFLIGHT_NOT_COMPLIANT,
    PreflightSentinel,
)
from agentkit.telemetry.contract.records import ExecutionEventRecord
from agentkit.telemetry.contract.results import ContractStatus
from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType


def _event(event_type: EventType, *, story_id: str = "AG3-001") -> ExecutionEventRecord:
    return ExecutionEventRecord(
        project_key="proj",
        story_id=story_id,
        run_id="run-001",
        event_id=f"evt-{event_type.value}-{id(object())}",
        event_type=event_type.value,
        occurred_at=datetime.now(UTC),
        source_component="test",
        severity="info",
    )


def test_compliant_stream_passes() -> None:
    events = [
        _event(EventType.PREFLIGHT_REQUEST),
        _event(EventType.PREFLIGHT_REQUEST),
        _event(EventType.PREFLIGHT_RESPONSE),
        _event(EventType.PREFLIGHT_RESPONSE),
        _event(EventType.PREFLIGHT_COMPLIANT),
        _event(EventType.PREFLIGHT_COMPLIANT),
    ]
    result = PreflightSentinel().check_balance(events)
    assert result.status is ContractStatus.PASS
    assert result.rule_id == PREFLIGHT_BALANCE_RULE_ID


def test_compliant_imbalance_fails_with_rule_id() -> None:
    events = [
        _event(EventType.PREFLIGHT_REQUEST),
        _event(EventType.PREFLIGHT_REQUEST),
        _event(EventType.PREFLIGHT_RESPONSE),
        _event(EventType.PREFLIGHT_RESPONSE),
        _event(EventType.PREFLIGHT_COMPLIANT),
    ]
    result = PreflightSentinel().check_balance(events)
    assert result.status is ContractStatus.FAIL
    assert result.rule_id == "FK-68 §68.9.2"
    assert PREFLIGHT_NOT_COMPLIANT in result.detail


def test_missing_response_fails() -> None:
    # request == compliant but no response -> NOT compliant (FK-68 §68.9.3).
    events = [
        _event(EventType.PREFLIGHT_REQUEST),
        _event(EventType.PREFLIGHT_COMPLIANT),
    ]
    result = PreflightSentinel().check_balance(events)
    assert result.status is ContractStatus.FAIL
    assert PREFLIGHT_NOT_COMPLIANT in result.detail


def test_empty_stream_is_missing_not_pass() -> None:
    # FK-68 §68.9.3: preflight is mandatory. An empty stream fails-closed.
    result = PreflightSentinel().check_balance([])
    assert result.status is ContractStatus.FAIL
    assert result.rule_id == PREFLIGHT_BALANCE_RULE_ID
    assert PREFLIGHT_MISSING in result.detail


def test_missing_emits_violation_event() -> None:
    emitter = MemoryEmitter()
    events = [_event(EventType.PREFLIGHT_RESPONSE)]  # no request -> MISSING
    result = PreflightSentinel().check_balance(events, emitter=emitter)
    assert result.status is ContractStatus.FAIL
    emitted = emitter.all_events
    assert len(emitted) == 1
    violation = emitted[0]
    assert violation.event_type is EventType.PREFLIGHT_COMPLIANCE_VIOLATION
    assert violation.story_id == "AG3-001"
    assert violation.payload["preflight_request"] == 0
    assert violation.payload["failure_code"] == PREFLIGHT_MISSING
    assert violation.payload["rule_id"] == PREFLIGHT_BALANCE_RULE_ID


def test_imbalance_emits_violation_event() -> None:
    emitter = MemoryEmitter()
    events = [
        _event(EventType.PREFLIGHT_REQUEST),
        _event(EventType.PREFLIGHT_RESPONSE),
        _event(EventType.PREFLIGHT_COMPLIANT),
        _event(EventType.PREFLIGHT_COMPLIANT),
    ]
    result = PreflightSentinel().check_balance(events, emitter=emitter)
    assert result.status is ContractStatus.FAIL
    emitted = emitter.all_events
    assert len(emitted) == 1
    violation = emitted[0]
    assert violation.event_type is EventType.PREFLIGHT_COMPLIANCE_VIOLATION
    assert violation.payload["preflight_request"] == 1
    assert violation.payload["preflight_response"] == 1
    assert violation.payload["preflight_compliant"] == 2
    assert violation.payload["failure_code"] == PREFLIGHT_NOT_COMPLIANT


def test_compliant_stream_emits_nothing() -> None:
    emitter = MemoryEmitter()
    events = [
        _event(EventType.PREFLIGHT_REQUEST),
        _event(EventType.PREFLIGHT_RESPONSE),
        _event(EventType.PREFLIGHT_COMPLIANT),
    ]
    PreflightSentinel().check_balance(events, emitter=emitter)
    assert emitter.all_events == []
