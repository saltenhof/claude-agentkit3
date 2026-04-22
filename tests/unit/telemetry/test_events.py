"""Unit tests for agentkit.telemetry.events."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.telemetry.events import Event, EventType


class TestEventType:
    """Tests for the EventType enum."""

    def test_flow_start_value(self) -> None:
        assert EventType.FLOW_START == "flow_start"

    def test_flow_end_value(self) -> None:
        assert EventType.FLOW_END == "flow_end"

    def test_node_result_value(self) -> None:
        assert EventType.NODE_RESULT == "node_result"

    def test_override_applied_value(self) -> None:
        assert EventType.OVERRIDE_APPLIED == "override_applied"

    def test_review_request_value(self) -> None:
        assert EventType.REVIEW_REQUEST == "review_request"

    def test_error_value(self) -> None:
        assert EventType.ERROR == "error"

    def test_warning_value(self) -> None:
        assert EventType.WARNING == "warning"

    def test_is_str_enum(self) -> None:
        assert isinstance(EventType.FLOW_START, str)

    def test_all_expected_members(self) -> None:
        expected = {
            "AGENT_START",
            "AGENT_END",
            "INCREMENT_COMMIT",
            "DRIFT_CHECK",
            "FLOW_START",
            "FLOW_END",
            "NODE_RESULT",
            "OVERRIDE_APPLIED",
            "REVIEW_REQUEST",
            "REVIEW_RESPONSE",
            "REVIEW_COMPLIANT",
            "LLM_CALL",
            "ADVERSARIAL_START",
            "ADVERSARIAL_SPARRING",
            "ADVERSARIAL_TEST_CREATED",
            "ADVERSARIAL_TEST_EXECUTED",
            "ADVERSARIAL_END",
            "PREFLIGHT_REQUEST",
            "PREFLIGHT_RESPONSE",
            "PREFLIGHT_COMPLIANT",
            "REVIEW_DIVERGENCE",
            "INTEGRITY_VIOLATION",
            "SESSION_RUN_BINDING_CREATED",
            "SESSION_RUN_BINDING_REMOVED",
            "STORY_EXECUTION_REGIME_ACTIVATED",
            "STORY_EXECUTION_REGIME_DEACTIVATED",
            "BINDING_INVALID_DETECTED",
            "LOCAL_EDGE_BUNDLE_MATERIALIZED",
            "EDGE_OPERATION_RECONCILED",
            "WEB_CALL",
            "IMPACT_VIOLATION_CHECK",
            "DOC_FIDELITY_CHECK",
            "VECTORDB_SEARCH",
            "COMPACTION_EVENT",
            "ERROR",
            "WARNING",
        }
        actual = {m.name for m in EventType}
        assert actual == expected


class TestEvent:
    """Tests for the Event dataclass."""

    def test_construction_minimal(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        assert evt.story_id == "AG3-001"
        assert evt.event_type == EventType.FLOW_START

    def test_frozen_enforcement(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        with pytest.raises(AttributeError):
            evt.story_id = "AG3-002"  # type: ignore[misc]

    def test_default_timestamp_is_set(self) -> None:
        before = datetime.now(UTC)
        evt = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        after = datetime.now(UTC)
        assert before <= evt.timestamp <= after

    def test_default_payload_is_empty_dict(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        assert evt.payload == {}

    def test_default_phase_is_none(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        assert evt.phase is None

    def test_default_project_key_is_none(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        assert evt.project_key is None

    def test_default_event_id_is_none(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        assert evt.event_id is None

    def test_default_source_component_is_telemetry_service(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        assert evt.source_component == "telemetry_service"

    def test_default_severity_is_info(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        assert evt.severity == "info"

    def test_default_run_id_is_none(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        assert evt.run_id is None

    def test_construction_full(self) -> None:
        ts = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)
        payload = {"key": "value", "count": 42}
        evt = Event(
            story_id="AG3-042",
            event_type=EventType.NODE_RESULT,
            timestamp=ts,
            project_key="demo-project",
            event_id="evt-001",
            source_component="pipeline_engine",
            severity="warning",
            phase="verify",
            flow_id="implementation",
            node_id="verify",
            payload=payload,
            run_id="run-abc",
        )
        assert evt.story_id == "AG3-042"
        assert evt.event_type == EventType.NODE_RESULT
        assert evt.timestamp == ts
        assert evt.project_key == "demo-project"
        assert evt.event_id == "evt-001"
        assert evt.source_component == "pipeline_engine"
        assert evt.severity == "warning"
        assert evt.phase == "verify"
        assert evt.flow_id == "implementation"
        assert evt.node_id == "verify"
        assert evt.payload == payload
        assert evt.run_id == "run-abc"


class TestEventToDict:
    """Tests for Event.to_dict() serialisation."""

    def test_to_dict_keys(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.FLOW_START)
        d = evt.to_dict()
        assert set(d.keys()) == {
            "project_key",
            "story_id",
            "event_id",
            "event_type",
            "timestamp",
            "source_component",
            "severity",
            "phase",
            "flow_id",
            "node_id",
            "payload",
            "run_id",
        }

    def test_to_dict_values(self) -> None:
        ts = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
        evt = Event(
            story_id="AG3-010",
            event_type=EventType.AGENT_START,
            timestamp=ts,
            project_key="demo-project",
            event_id="evt-xyz",
            source_component="hook",
            severity="info",
            phase="implementation",
            flow_id="implementation",
            node_id="worker",
            payload={"worker": "code"},
            run_id="run-xyz",
        )
        d = evt.to_dict()
        assert d["project_key"] == "demo-project"
        assert d["story_id"] == "AG3-010"
        assert d["event_id"] == "evt-xyz"
        assert d["event_type"] == "agent_start"
        assert d["timestamp"] == ts.isoformat()
        assert d["source_component"] == "hook"
        assert d["severity"] == "info"
        assert d["phase"] == "implementation"
        assert d["flow_id"] == "implementation"
        assert d["node_id"] == "worker"
        assert d["payload"] == {"worker": "code"}
        assert d["run_id"] == "run-xyz"

    def test_to_dict_none_fields(self) -> None:
        evt = Event(story_id="AG3-001", event_type=EventType.ERROR)
        d = evt.to_dict()
        assert d["project_key"] is None
        assert d["event_id"] is None
        assert d["phase"] is None
        assert d["flow_id"] is None
        assert d["node_id"] is None
        assert d["run_id"] is None
        assert d["payload"] == {}
