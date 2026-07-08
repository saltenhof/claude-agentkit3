"""Control-plane service for canonical telemetry ingest."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import (
    TelemetryEventAccepted,
    TelemetryEventIngestRequest,
    TelemetryEventQueryResponse,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    append_execution_event_global,
)
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

if TYPE_CHECKING:
    from collections.abc import Callable


def _default_event_reader(
    project_key: str, story_id: str, event_type: str | None
) -> list[ExecutionEventRecord]:
    # Route through the explicit story-read repository surface so the restricted
    # ``load_*_global`` loader import stays inside it (architecture-conformance
    # AC004); the control-plane service never imports the loader directly.
    from agentkit.backend.state_backend.store.story_read_repository import (
        StateBackendStoryReadRepository,
    )

    return StateBackendStoryReadRepository().query_execution_events(
        project_key, story_id, event_type=event_type
    )


class ControlPlaneTelemetryService:
    """Persist and read canonical telemetry events from the control plane."""

    def __init__(
        self,
        *,
        event_writer: Callable[[ExecutionEventRecord], None] = (
            append_execution_event_global
        ),
        event_reader: Callable[
            [str, str, str | None], list[ExecutionEventRecord]
        ] = _default_event_reader,
    ) -> None:
        self._event_writer = event_writer
        self._event_reader = event_reader

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

    def query_events(
        self,
        *,
        project_key: str,
        story_id: str,
        event_type: str | None = None,
    ) -> TelemetryEventQueryResponse:
        """Read canonical execution events for one scope (AG3-129).

        Backs the hook's REST event-emitter ``query`` so the Dev side reads
        counts via the core instead of opening the database directly (FK-10
        §10.1.0 I1).

        Args:
            project_key: The project scope to read.
            story_id: The story scope to read.
            event_type: Optional canonical event-type filter.

        Returns:
            The read result carrying the matching events as wire objects.
        """
        records = self._event_reader(project_key, story_id, event_type)
        return TelemetryEventQueryResponse(
            events=[execution_event_to_wire(record) for record in records]
        )


def execution_event_to_wire(record: ExecutionEventRecord) -> dict[str, object]:
    """Serialize a canonical execution event to the AG3-129 read wire shape.

    The key set is consumed by the hook-side REST event emitter's
    ``_wire_to_event`` mapper; both sides MUST agree on these keys (a contract
    test pins the round-trip).

    Args:
        record: The canonical execution-event record.

    Returns:
        A JSON-safe wire dict.
    """
    return {
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
        "payload": dict(record.payload),
    }


def _next_event_id() -> str:
    return f"evt-{uuid.uuid4().hex}"
