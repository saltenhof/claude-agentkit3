"""Unit tests for agentkit.telemetry.events."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.telemetry.events import Event, EventType


class TestEventType:
    """Tests for the EventType enum."""

    def test_phase_started_value(self) -> None:
        assert EventType.PHASE_STARTED == "phase_started"

    def test_phase_completed_value(self) -> None:
        assert EventType.PHASE_COMPLETED == "phase_completed"

    def test_phase_failed_value(self) -> None:
        assert EventType.PHASE_FAILED == "phase_failed"

    def test_qa_decision_value(self) -> None:
        assert EventType.QA_DECISION == "qa_decision"

    def test_worker_spawned_value(self) -> None:
        assert EventType.WORKER_SPAWNED == "worker_spawned"

    def test_error_value(self) -> None:
        assert EventType.ERROR == "error"

    def test_warning_value(self) -> None:
        assert EventType.WARNING == "warning"

    def test_issue_closed_value(self) -> None:
        assert EventType.ISSUE_CLOSED == "issue_closed"

    def test_is_str_enum(self) -> None:
        assert isinstance(EventType.PHASE_STARTED, str)

    def test_all_expected_members(self) -> None:
        expected = {
            "PHASE_STARTED",
            "PHASE_COMPLETED",
            "PHASE_FAILED",
            "PHASE_YIELDED",
            "PHASE_RESUMED",
            "QA_LAYER_STARTED",
            "QA_LAYER_COMPLETED",
            "QA_DECISION",
            "WORKER_SPAWNED",
            "WORKER_COMPLETED",
            "GUARD_EVALUATED",
            "INTEGRITY_CHECK",
            "ISSUE_CLOSED",
            "ISSUE_CREATED",
            "ERROR",
            "WARNING",
        }
        actual = {m.name for m in EventType}
        assert actual == expected


class TestEvent:
    """Tests for the Event dataclass."""

    def test_construction_minimal(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.PHASE_STARTED)
        assert evt.story_id == "AG3-001"
        assert evt.event_type == EventType.PHASE_STARTED

    def test_frozen_enforcement(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.PHASE_STARTED)
        with pytest.raises(AttributeError):
            evt.story_id = "AG3-002"  # type: ignore[misc]

    def test_default_timestamp_is_set(self) -> None:
        before = datetime.now(UTC)
        evt = Event(story_id="AG3-001", event_type=EventType.PHASE_STARTED)
        after = datetime.now(UTC)
        assert before <= evt.timestamp <= after

    def test_default_payload_is_empty_dict(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.PHASE_STARTED)
        assert evt.payload == {}

    def test_default_phase_is_none(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.PHASE_STARTED)
        assert evt.phase is None

    def test_default_run_id_is_none(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.PHASE_STARTED)
        assert evt.run_id is None

    def test_construction_full(self) -> None:
        ts = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)
        payload = {"key": "value", "count": 42}
        evt = Event(
            story_id="AG3-042",
            event_type=EventType.QA_DECISION,
            timestamp=ts,
            phase="verify",
            payload=payload,
            run_id="run-abc",
        )
        assert evt.story_id == "AG3-042"
        assert evt.event_type == EventType.QA_DECISION
        assert evt.timestamp == ts
        assert evt.phase == "verify"
        assert evt.payload == payload
        assert evt.run_id == "run-abc"


class TestEventToDict:
    """Tests for Event.to_dict() serialisation."""

    def test_to_dict_keys(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.PHASE_STARTED)
        d = evt.to_dict()
        assert set(d.keys()) == {
            "story_id",
            "event_type",
            "timestamp",
            "phase",
            "payload",
            "run_id",
        }

    def test_to_dict_values(self) -> None:
        ts = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
        evt = Event(
            story_id="AG3-010",
            event_type=EventType.WORKER_SPAWNED,
            timestamp=ts,
            phase="implementation",
            payload={"worker": "code"},
            run_id="run-xyz",
        )
        d = evt.to_dict()
        assert d["story_id"] == "AG3-010"
        assert d["event_type"] == "worker_spawned"
        assert d["timestamp"] == ts.isoformat()
        assert d["phase"] == "implementation"
        assert d["payload"] == {"worker": "code"}
        assert d["run_id"] == "run-xyz"

    def test_to_dict_none_fields(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.ERROR)
        d = evt.to_dict()
        assert d["phase"] is None
        assert d["run_id"] is None
        assert d["payload"] == {}
