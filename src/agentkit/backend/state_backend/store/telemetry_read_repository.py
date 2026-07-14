"""StateBackendProjectTelemetryEventSource — productive telemetry read adapter (AG3-127).

Productive implementation of the consumer-owned ``ProjectTelemetryEventSource``
Protocol (``agentkit.backend.telemetry.repository``), backing the telemetry-BC
project-scoped execution-event SSE read edge (FK-07 §7.6/§7.8). Mirrors
``StateBackendStoryReadRepository`` (AG3-126):

- This adapter is the ONLY place that knows the global project execution-event
  loader (``load_execution_events_for_project_global``); the telemetry BC
  (``telemetry.sse_stream`` / ``telemetry.http.routes``) depends solely on the
  Protocol and never imports this loader.
- Wired in the composition root (``build_project_telemetry_event_source`` /
  ``_build_default_telemetry_routes``); ``telemetry`` never imports this module.
- Fail-closed (FK-07 §7.7.5 / story §2.1.5): the read delegates 1:1 to the
  state-backend loader unchanged — a missing table propagates the underlying
  backend error, a legitimately-empty project returns an empty list. No silent
  empty-OK masks a missing backend here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.state_backend.story_lifecycle_store import (
    list_pending_takeover_approvals_global,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_execution_events_by_type_global,
    load_execution_events_for_project_global,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane.records import TakeoverApprovalRecord
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord


@dataclass(frozen=True)
class StateBackendProjectTelemetryEventSource:
    """State-backend implementation of ``ProjectTelemetryEventSource`` (AG3-127).

    The single method delegates 1:1 to the global project execution-event
    loader, preserving the established fail-closed and empty-list contract. The
    loader is an inherently global read (no ``store_dir`` parameter).
    """

    def events_for_project(
        self,
        project_key: str,
        *,
        limit: int = 200,
    ) -> list[ExecutionEventRecord]:
        """Return recent execution events for one project (empty list when none)."""
        return load_execution_events_for_project_global(project_key, limit=limit)

    def pending_takeover_approvals_for_project(
        self,
        project_key: str | None,
    ) -> tuple[TakeoverApprovalRecord, ...]:
        """Return pending approvals for one project or all projects."""
        return list_pending_takeover_approvals_global(project_key)

    def takeover_approval_events_global(
        self,
        *,
        limit: int = 200,
    ) -> list[ExecutionEventRecord]:
        """Return recent cross-project takeover approval change events."""
        return load_execution_events_by_type_global(
            "takeover_approval_changed",
            limit=limit,
        )


__all__ = ["StateBackendProjectTelemetryEventSource"]
