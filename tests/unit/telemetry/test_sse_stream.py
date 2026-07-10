from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane.ownership import TakeoverApprovalStatus
from agentkit.backend.control_plane.records import TakeoverApprovalRecord
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.sse_stream import (
    parse_project_topics,
    project_event_to_sse,
    render_heartbeat,
    render_project_snapshot,
)


def _record(
    *,
    project_key: str = "tenant-a",
    event_id: str = "evt-1",
    event_type: str = "agent_start",
    topic: str | None = None,
    phase: str | None = None,
) -> ExecutionEventRecord:
    return ExecutionEventRecord(
        project_key=project_key,
        story_id="AG3-100",
        run_id="run-1",
        event_id=event_id,
        event_type=event_type,
        occurred_at=datetime(2026, 5, 4, 10, 0, tzinfo=UTC),
        source_component="telemetry",
        severity="info",
        phase=phase,
        payload=({"topic": topic} if topic is not None else {}),
    )


def test_project_event_to_sse_uses_payload_topic() -> None:
    envelope = project_event_to_sse(_record(topic="stories"))

    assert envelope.event == "stories"
    assert envelope.data["project_key"] == "tenant-a"
    assert envelope.data["event_id"] == "evt-1"


def test_takeover_approval_changed_routes_to_governance_before_phase() -> None:
    envelope = project_event_to_sse(
        _record(event_type="takeover_approval_changed", phase="ownership")
    )

    assert envelope.event == "governance"


def test_render_project_snapshot_filters_topics_and_adds_heartbeat() -> None:
    payload = render_project_snapshot(
        [_record(event_id="evt-1", topic="stories"), _record(event_id="evt-2", topic="governance")],
        topics={"governance"},
    ).decode("utf-8")

    assert "event: governance" in payload
    assert "evt-2" in payload
    assert "evt-1" not in payload
    assert "event: heartbeat" in payload


def test_render_project_snapshot_includes_pending_takeover_approvals_on_governance_topic() -> None:
    approval = TakeoverApprovalRecord(
        approval_id="approval-1",
        project_key="tenant-a",
        story_id="AG3-148",
        run_id="run-1",
        requested_by_session_id="sess-agent",
        requested_by_principal_type="interactive_agent",
        reason="owner unavailable",
        challenge_ref="challenge-1",
        status=TakeoverApprovalStatus.PENDING,
        requested_at=datetime(2026, 5, 4, 10, 0, tzinfo=UTC),
        expires_at=datetime(2026, 5, 4, 10, 15, tzinfo=UTC),
    )

    payload = render_project_snapshot(
        [],
        topics={"governance"},
        pending_takeover_approvals=[approval],
    ).decode("utf-8")

    assert "event: governance" in payload
    assert '"event_type": "pending_takeover_approval"' in payload
    assert '"approval_id": "approval-1"' in payload
    assert '"challenge_id": "challenge-1"' in payload
    assert '"requested_by_principal_type": "interactive_agent"' in payload


def test_render_heartbeat_is_sse_json_payload() -> None:
    heartbeat = render_heartbeat().decode("utf-8")

    assert heartbeat.startswith("event: heartbeat\n")
    data = heartbeat.split("data: ", maxsplit=1)[1].strip()
    assert json.loads(data) == {"type": "heartbeat"}


def test_parse_project_topics_defaults_and_rejects_unknown() -> None:
    assert "stories" in parse_project_topics(None)
    assert parse_project_topics("stories,phases") == frozenset({"stories", "phases"})

    with pytest.raises(ValueError, match="Unknown SSE topic"):
        parse_project_topics("stories,unknown")
