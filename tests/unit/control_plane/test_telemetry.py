from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.control_plane.models import TelemetryEventIngestRequest
from agentkit.control_plane.telemetry import ControlPlaneTelemetryService
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from agentkit.state_backend import ExecutionEventRecord


def test_ingest_event_persists_canonical_execution_record() -> None:
    written: list[dict[str, object]] = []

    def writer(record: ExecutionEventRecord) -> None:
        written.append(record.__dict__)

    service = ControlPlaneTelemetryService(event_writer=writer)
    accepted = service.ingest_event(
        TelemetryEventIngestRequest(
            project_key="tenant-a",
            story_id="AG3-501",
            run_id="run-501",
            event_type=EventType.AGENT_START,
            occurred_at=datetime(2026, 4, 20, 10, 15, tzinfo=UTC),
            source_component="control-plane",
            phase="implementation",
            flow_id="implementation",
            node_id="implementation",
            payload={"channel": "rest"},
        ),
    )

    assert accepted.status == "accepted"
    assert accepted.event_id.startswith("evt-")
    assert written == [
        {
            "project_key": "tenant-a",
            "story_id": "AG3-501",
            "run_id": "run-501",
            "event_id": accepted.event_id,
            "event_type": "agent_start",
            "occurred_at": datetime(2026, 4, 20, 10, 15, tzinfo=UTC),
            "source_component": "control-plane",
            "severity": "info",
            "phase": "implementation",
            "flow_id": "implementation",
            "node_id": "implementation",
            "payload": {"channel": "rest"},
        },
    ]


def test_ingest_event_keeps_explicit_event_id() -> None:
    seen_event_ids: list[str] = []

    def writer(record: ExecutionEventRecord) -> None:
        seen_event_ids.append(record.event_id)

    service = ControlPlaneTelemetryService(event_writer=writer)
    accepted = service.ingest_event(
        TelemetryEventIngestRequest(
            project_key="tenant-b",
            story_id="AG3-777",
            run_id="run-777",
            event_type=EventType.FLOW_START,
            occurred_at=datetime(2026, 4, 20, 11, 0, tzinfo=UTC),
            source_component="control-plane",
            event_id="evt-fixed-777",
        ),
    )

    assert accepted.event_id == "evt-fixed-777"
    assert seen_event_ids == ["evt-fixed-777"]
