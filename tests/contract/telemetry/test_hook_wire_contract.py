"""Contract: the AG3-129 telemetry read wire shape round-trips.

The server serializer (``control_plane.telemetry.execution_event_to_wire``) and
the hook emitter deserializer (``telemetry.rest_emitter._wire_to_event``) MUST
agree on the key set; this pins the round-trip so the two sides cannot drift.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.backend.control_plane.telemetry import execution_event_to_wire
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType
from agentkit.backend.telemetry.rest_emitter import _wire_to_event


def test_execution_event_wire_round_trip() -> None:
    record = ExecutionEventRecord(
        project_key="tenant-a",
        story_id="AG3-129",
        run_id="run-129",
        event_id="evt-abc",
        event_type=EventType.INCREMENT_COMMIT.value,
        occurred_at=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        source_component="review_guard",
        severity="info",
        phase="implementation",
        flow_id="flow-1",
        node_id="node-1",
        payload={"marker": "x", "count": 3},
    )

    event = _wire_to_event(execution_event_to_wire(record))

    assert event.story_id == record.story_id
    assert event.event_type == EventType.INCREMENT_COMMIT
    assert event.timestamp == record.occurred_at
    assert event.project_key == record.project_key
    assert event.run_id == record.run_id
    assert event.event_id == record.event_id
    assert event.source_component == record.source_component
    assert event.severity == record.severity
    assert event.phase == record.phase
    assert event.flow_id == record.flow_id
    assert event.node_id == record.node_id
    assert event.payload == record.payload


def test_wire_to_event_tolerates_absent_optionals() -> None:
    record = ExecutionEventRecord(
        project_key="tenant-a",
        story_id="AG3-129",
        run_id="run-129",
        event_id="evt-abc",
        event_type=EventType.INCREMENT_COMMIT.value,
        occurred_at=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        source_component="review_guard",
        severity="info",
    )

    event = _wire_to_event(execution_event_to_wire(record))

    assert event.phase is None
    assert event.flow_id is None
    assert event.node_id is None
    assert event.payload == {}
