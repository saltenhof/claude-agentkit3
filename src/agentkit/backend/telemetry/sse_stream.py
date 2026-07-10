"""SSE stream composition for project-scoped telemetry live updates."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from agentkit.backend.control_plane.records import TakeoverApprovalRecord
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
    from agentkit.backend.telemetry.repository import ProjectTelemetryEventSource

ProjectSseTopic = Literal[
    "stories",
    "phases",
    "gates",
    "governance",
    "closure",
    "artifacts",
    "telemetry",
    "kpi",
    "planning",
    "failure_corpus",
    "coverage",
]

PROJECT_SSE_TOPICS: frozenset[ProjectSseTopic] = frozenset(
    {
        "stories",
        "phases",
        "gates",
        "governance",
        "closure",
        "artifacts",
        "telemetry",
        "kpi",
        "planning",
        "failure_corpus",
        "coverage",
    },
)


@dataclass(frozen=True)
class SseEnvelope:
    """One typed SSE event envelope."""

    event: str
    data: dict[str, object]


def parse_project_topics(raw_topics: str | None) -> frozenset[ProjectSseTopic]:
    """Parse a comma-separated project SSE topic filter."""
    if raw_topics is None or not raw_topics.strip():
        return PROJECT_SSE_TOPICS
    topics: set[ProjectSseTopic] = set()
    invalid: list[str] = []
    for raw_topic in raw_topics.split(","):
        topic = raw_topic.strip()
        if not topic:
            continue
        if topic not in PROJECT_SSE_TOPICS:
            invalid.append(topic)
            continue
        topics.add(topic)
    if invalid:
        raise ValueError(f"Unknown SSE topic: {', '.join(sorted(invalid))}")
    return frozenset(topics or PROJECT_SSE_TOPICS)


def project_event_to_sse(record: ExecutionEventRecord) -> SseEnvelope:
    """Convert one execution-event record into a project SSE envelope."""
    topic = _topic_for_record(record)
    return SseEnvelope(
        event=topic,
        data={
            "project_key": record.project_key,
            "story_id": record.story_id,
            "run_id": record.run_id,
            "event_id": record.event_id,
            "event_type": record.event_type,
            "occurred_at": record.occurred_at.isoformat(),
            "source_component": record.source_component,
            "severity": record.severity,
            "phase": record.phase,
            "flow_id": record.flow_id,
            "node_id": record.node_id,
            "payload": record.payload,
        },
    )


def render_sse_event(envelope: SseEnvelope) -> bytes:
    """Render one SSE envelope as bytes."""
    payload = json.dumps(envelope.data, sort_keys=True, default=str)
    lines = [f"event: {envelope.event}", f"data: {payload}", ""]
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_heartbeat() -> bytes:
    """Render one SSE heartbeat event."""
    return render_sse_event(
        SseEnvelope(
            event="heartbeat",
            data={"type": "heartbeat"},
        ),
    )


def render_project_snapshot(
    records: Sequence[ExecutionEventRecord],
    *,
    topics: Iterable[ProjectSseTopic],
    pending_takeover_approvals: Sequence[TakeoverApprovalRecord] = (),
) -> bytes:
    """Render current matching project events as SSE bytes."""
    allowed = set(topics)
    chunks: list[bytes] = []
    if "governance" in allowed:
        chunks.extend(
            render_sse_event(_takeover_approval_snapshot_envelope(approval))
            for approval in pending_takeover_approvals
        )
    for record in records:
        envelope = project_event_to_sse(record)
        if envelope.event in allowed:
            chunks.append(render_sse_event(envelope))
    chunks.append(render_heartbeat())
    return b"".join(chunks)


def iter_project_sse_stream(
    *,
    project_key: str,
    source: ProjectTelemetryEventSource,
    topics: Iterable[ProjectSseTopic],
    heartbeat_interval_seconds: float = 30.0,
    poll_interval_seconds: float = 1.0,
) -> Iterator[bytes]:
    """Yield a lossy project SSE stream.

    The stream keeps only an in-memory set of already emitted event ids for
    this connection. It has no sequence cursor and performs a fresh project
    read on reconnect, matching the FK-72/FK-91 lossy contract.
    """
    allowed = frozenset(topics)
    seen_event_ids: set[str] = set()
    last_heartbeat = 0.0
    while True:
        yield from _iter_pending_takeover_approval_events(
            project_key=project_key,
            source=source,
            allowed=allowed,
            seen_event_ids=seen_event_ids,
        )
        yield from _iter_project_execution_events(
            project_key=project_key,
            source=source,
            allowed=allowed,
            seen_event_ids=seen_event_ids,
        )
        current_time = time.monotonic()
        if current_time - last_heartbeat >= heartbeat_interval_seconds:
            yield render_heartbeat()
            last_heartbeat = current_time
        time.sleep(poll_interval_seconds)


def _topic_for_record(record: ExecutionEventRecord) -> ProjectSseTopic:
    payload_topic = record.payload.get("topic")
    if isinstance(payload_topic, str) and payload_topic in PROJECT_SSE_TOPICS:
        return payload_topic
    if record.event_type in {
        "integrity_violation",
        "edge_operation_reconciled",
        "takeover_approval_changed",
    }:
        return "governance"
    if record.phase is not None:
        return "phases"
    if record.event_type.startswith("story_"):
        return "stories"
    return "telemetry"


def _iter_pending_takeover_approval_events(
    *,
    project_key: str,
    source: ProjectTelemetryEventSource,
    allowed: frozenset[ProjectSseTopic],
    seen_event_ids: set[str],
) -> Iterator[bytes]:
    if "governance" not in allowed:
        return
    for approval in source.pending_takeover_approvals_for_project(project_key):
        approval_key = f"takeover-approval:{approval.approval_id}:{approval.status.value}"
        if approval_key in seen_event_ids:
            continue
        seen_event_ids.add(approval_key)
        yield render_sse_event(_takeover_approval_snapshot_envelope(approval))


def _iter_project_execution_events(
    *,
    project_key: str,
    source: ProjectTelemetryEventSource,
    allowed: frozenset[ProjectSseTopic],
    seen_event_ids: set[str],
) -> Iterator[bytes]:
    for record in source.events_for_project(project_key):
        if record.event_id in seen_event_ids:
            continue
        seen_event_ids.add(record.event_id)
        envelope = project_event_to_sse(record)
        if envelope.event in allowed:
            yield render_sse_event(envelope)


def _takeover_approval_snapshot_envelope(
    approval: TakeoverApprovalRecord,
) -> SseEnvelope:
    return SseEnvelope(
        event="governance",
        data={
            "project_key": approval.project_key,
            "story_id": approval.story_id,
            "run_id": approval.run_id,
            "event_type": "pending_takeover_approval",
            "approval_id": approval.approval_id,
            "requested_by_session_id": approval.requested_by_session_id,
            "requested_by_principal_type": approval.requested_by_principal_type,
            "reason": approval.reason,
            "challenge_id": approval.challenge_ref,
            "status": approval.status.value,
            "requested_at": approval.requested_at.isoformat(),
            "expires_at": approval.expires_at.isoformat(),
        },
    )


__all__ = [
    "PROJECT_SSE_TOPICS",
    "ProjectSseTopic",
    "SseEnvelope",
    "iter_project_sse_stream",
    "parse_project_topics",
    "project_event_to_sse",
    "render_heartbeat",
    "render_project_snapshot",
    "render_sse_event",
]
