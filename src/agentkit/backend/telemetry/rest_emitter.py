"""REST-backed telemetry emitter for the short-lived hook process (AG3-129).

FK-10 §10.1.0 I1 / §10.3.2: the Dev-side hook reports and reads telemetry via
the core's REST API (``/v1/telemetry/events``), never by opening the database
directly. This :class:`~agentkit.backend.telemetry.emitters.EventEmitter`
implementation replaces ``StateBackendEmitter`` in the hook path.

Blocking semantics (FK-30 "blockieren nie" for observability):

* ``emit`` is non-blocking -- a core-unreachable / rejected event is logged and
  dropped, NEVER re-routed to a direct-DB back door and NEVER raised.
* ``query`` preserves the pre-existing fail-soft read behaviour of
  ``StateBackendEmitter.query`` (a read fault returns ``[]``), so this migration
  does not silently change any guard's blocking effect; it only moves the read
  off the direct-DB path onto REST.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import TelemetryEventIngestRequest
from agentkit.backend.telemetry.events import Event, EventType

if TYPE_CHECKING:
    from agentkit.harness_client.projectedge.governance_client import (
        GovernanceEdgeClient,
    )

logger = logging.getLogger(__name__)

_ALLOWED_SEVERITIES = frozenset(
    {"debug", "info", "warning", "error", "critical"}
)


class RestEventEmitter:
    """Emit and query telemetry over the core REST API (no direct DB)."""

    def __init__(
        self,
        client: GovernanceEdgeClient,
        *,
        project_key: str,
        run_id: str,
        default_source_component: str = "telemetry_service",
        strict_query: bool = False,
    ) -> None:
        """Bind the emitter to a governance edge client and run scope.

        Args:
            client: The hook-side REST client (single shared transport).
            project_key: The active project scope (from the resolved edge
                bundle) used when an event omits its own ``project_key``.
            run_id: The active run scope used when an event omits its own
                ``run_id``.
            default_source_component: Source-component label applied when an
                event carries the generic ``telemetry_service`` default.
            strict_query: When ``True`` (enforcement readers, e.g. the web-call
                budget guard), ``query`` RAISES on a core-unreachable read rather
                than returning ``[]`` -- so a fail-closed guard never mistakes an
                unreadable counter for "zero events" (AC5 / §2.1.4). Observability
                emitters keep the default ``False`` (fail-soft ``[]``).
        """
        self._client = client
        self._project_key = project_key
        self._run_id = run_id
        self._default_source_component = default_source_component
        self._strict_query = strict_query

    def emit(self, event: Event) -> None:
        """Emit one event via REST. Never raises (non-blocking, FK-30).

        Args:
            event: The immutable event to report.
        """
        project_key = event.project_key or self._project_key
        run_id = event.run_id or self._run_id
        if not project_key or not run_id:
            logger.warning(
                "Telemetry emit degraded for %s: missing project_key or run_id",
                event.story_id,
            )
            return
        severity = event.severity if event.severity in _ALLOWED_SEVERITIES else "info"
        try:
            request = TelemetryEventIngestRequest(
                project_key=project_key,
                story_id=event.story_id,
                run_id=run_id,
                event_type=event.event_type,
                occurred_at=event.timestamp,
                source_component=self._source_component_for(event),
                severity=severity,
                event_id=event.event_id,
                phase=event.phase,
                flow_id=event.flow_id,
                node_id=event.node_id,
                payload=dict(event.payload),
            )
            self._client.emit_telemetry_event(request)
        except Exception:  # noqa: BLE001 -- telemetry emit never blocks (FK-30); no DB fallback.
            logger.warning(
                "Failed to emit event %s for %s via REST "
                "(non-blocking; event dropped, no direct-DB fallback)",
                event.event_type,
                event.story_id,
                exc_info=True,
            )

    def query(
        self, story_id: str, event_type: EventType | None = None
    ) -> list[Event]:
        """Query events for a story via REST. Fail-soft (returns ``[]``).

        Args:
            story_id: The story to query events for.
            event_type: Optional canonical event-type filter.

        Returns:
            Matching events, or ``[]`` when the core read is unavailable and this
            emitter is NOT strict (mirroring the pre-existing direct-DB read's
            fail-soft behaviour; no blocking-effect change, no direct-DB
            fallback).

        Raises:
            Exception: When ``strict_query`` is set and the core read fails --
                the enforcement caller must fail CLOSED (AC5 / §2.1.4), never
                read an unavailable counter as zero.
        """
        try:
            response = self._client.query_telemetry_events(
                project_key=self._project_key,
                story_id=story_id,
                event_type=event_type.value if event_type is not None else None,
            )
            return [_wire_to_event(item) for item in response.events]
        except Exception:  # noqa: BLE001 -- see strict_query branch; no DB fallback either way.
            if self._strict_query:
                # Fail CLOSED: an enforcement read must NOT degrade an unreachable
                # counter to ``[]`` (== zero). Re-raise so the guard blocks.
                raise
            logger.warning(
                "Failed to query events for %s via REST (returning empty)",
                story_id,
                exc_info=True,
            )
            return []

    def _source_component_for(self, event: Event) -> str:
        if (
            event.source_component == "telemetry_service"
            and self._default_source_component != "telemetry_service"
        ):
            return self._default_source_component
        return event.source_component


def _wire_to_event(item: dict[str, object]) -> Event:
    """Map one telemetry read wire object back to an :class:`Event`.

    Mirrors ``control_plane.telemetry.execution_event_to_wire`` (a contract test
    pins the round-trip).

    Args:
        item: One wire event object from the query response.

    Returns:
        The reconstructed :class:`Event`.
    """
    return Event(
        story_id=str(item["story_id"]),
        event_type=EventType(str(item["event_type"])),
        timestamp=datetime.fromisoformat(str(item["occurred_at"])),
        project_key=_opt_str(item.get("project_key")),
        event_id=_opt_str(item.get("event_id")),
        source_component=str(item.get("source_component", "telemetry_service")),
        severity=str(item.get("severity", "info")),
        phase=_opt_str(item.get("phase")),
        flow_id=_opt_str(item.get("flow_id")),
        node_id=_opt_str(item.get("node_id")),
        payload=_as_payload(item.get("payload")),
        run_id=_opt_str(item.get("run_id")),
    )


def _opt_str(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _as_payload(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


__all__ = ["RestEventEmitter"]
