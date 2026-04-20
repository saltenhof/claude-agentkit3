"""Control-plane service for canonical telemetry ingest."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from agentkit.control_plane.models import (
    TelemetryEventAccepted,
    TelemetryEventIngestRequest,
)
from agentkit.state_backend import ExecutionEventRecord, append_execution_event_global

if TYPE_CHECKING:
    from collections.abc import Callable


class ControlPlaneTelemetryService:
    """Persist canonical telemetry events from the control plane."""

    def __init__(
        self,
        *,
        event_writer: Callable[[ExecutionEventRecord], None] = (
            append_execution_event_global
        ),
    ) -> None:
        self._event_writer = event_writer

    def ingest_event(
        self,
        request: TelemetryEventIngestRequest,
    ) -> TelemetryEventAccepted:
        """Validate and persist one canonical telemetry event."""

        event_id = request.event_id or _next_event_id()
        self._event_writer(
            ExecutionEventRecord(
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=request.run_id,
                event_id=event_id,
                event_type=request.event_type.value,
                occurred_at=request.occurred_at,
                source_component=request.source_component,
                severity=request.severity,
                phase=request.phase,
                flow_id=request.flow_id,
                node_id=request.node_id,
                payload=dict(request.payload),
            ),
        )
        return TelemetryEventAccepted(event_id=event_id)


def _next_event_id() -> str:
    return f"evt-{uuid.uuid4().hex}"
