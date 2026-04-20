"""Canonical telemetry storage over the configured state backend."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from agentkit.state_backend import (
    ExecutionEventRecord,
    append_execution_event,
    load_execution_events,
    resolve_runtime_scope,
)
from agentkit.telemetry.events import Event, EventType

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class StateBackendEmitter:
    """Persistent telemetry emitter backed by the canonical state backend."""

    def __init__(
        self,
        story_dir: Path,
        *,
        default_project_key: str | None = None,
        default_source_component: str = "telemetry_service",
    ) -> None:
        self._story_dir = story_dir
        self._default_project_key = default_project_key
        self._default_source_component = default_source_component

    def emit(self, event: Event) -> None:
        """Append an event to canonical runtime storage. Never raises.

        Args:
            event: The immutable event to persist.
        """
        try:
            project_key = self._resolve_project_key(event)
            run_id = self._resolve_run_id(event)
            if project_key is None or run_id is None:
                logger.warning(
                    "Telemetry append degraded for %s: missing project_key or run_id",
                    event.story_id,
                )
                return
            append_execution_event(
                self._story_dir,
                ExecutionEventRecord(
                    project_key=project_key,
                    story_id=event.story_id,
                    run_id=run_id,
                    event_id=event.event_id or _next_event_id(),
                    event_type=event.event_type.value,
                    occurred_at=event.timestamp,
                    source_component=self._source_component_for(event),
                    severity=event.severity,
                    phase=event.phase,
                    flow_id=event.flow_id,
                    node_id=event.node_id,
                    payload=dict(event.payload),
                ),
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to emit event %s for %s",
                event.event_type,
                event.story_id,
                exc_info=True,
            )

    def query(
        self, story_id: str, event_type: EventType | None = None
    ) -> list[Event]:
        """Query canonical execution events for one story.

        Args:
            story_id: The story to query events for.
            event_type: Optional filter for a specific event type.

        Returns:
            List of matching ``Event`` objects, ordered by occurrence time.
        """
        try:
            records = load_execution_events(
                self._story_dir,
                project_key=self._resolve_story_project_key(story_id),
                story_id=story_id,
                event_type=event_type.value if event_type is not None else None,
            )
            return [self._record_to_event(record) for record in records]
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to query events for %s",
                story_id,
                exc_info=True,
            )
            return []

    def _resolve_project_key(self, event: Event) -> str | None:
        if event.project_key:
            return event.project_key
        if self._default_project_key:
            return self._default_project_key
        return self._resolve_story_project_key(event.story_id)

    def _resolve_story_project_key(self, story_id: str) -> str | None:
        if self._default_project_key:
            return self._default_project_key
        scope = resolve_runtime_scope(self._story_dir)
        if scope.story_id == story_id and scope.project_key:
            return scope.project_key
        return None

    def _resolve_run_id(self, event: Event) -> str | None:
        if event.run_id:
            return event.run_id
        scope = resolve_runtime_scope(self._story_dir)
        if scope.story_id != event.story_id:
            return None
        return scope.run_id

    def _source_component_for(self, event: Event) -> str:
        if (
            event.source_component == "telemetry_service"
            and self._default_source_component != "telemetry_service"
        ):
            return self._default_source_component
        return event.source_component

    @staticmethod
    def _record_to_event(record: ExecutionEventRecord) -> Event:
        return Event(
            story_id=record.story_id,
            event_type=EventType(record.event_type),
            timestamp=record.occurred_at,
            project_key=record.project_key,
            event_id=record.event_id,
            source_component=record.source_component,
            severity=record.severity,
            phase=record.phase,
            flow_id=record.flow_id,
            node_id=record.node_id,
            payload=dict(record.payload),
            run_id=record.run_id,
        )


def _next_event_id() -> str:
    return f"evt-{uuid.uuid4().hex}"

__all__ = ["StateBackendEmitter"]
