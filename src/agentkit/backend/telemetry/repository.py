"""Published read port for project-scoped telemetry event reads (FK-07 §7.6).

This module defines :class:`ProjectTelemetryEventSource`, the consumer-owned read
port for the telemetry-and-events BC's project-scoped execution-event stream (the
SSE live-view read edge, FK-72 §72.8). It lives in the
``agentkit.backend.telemetry`` package (the BC), so the telemetry BC depends ONLY
on this Protocol and never imports the ``agentkit.backend.state_backend.store``
loader facade — the FK-07 §7.6/§7.8 architecture-conformance boundary
("Fachkomponenten/BFF haengen nicht an ``state_backend.store`` als generischer
Mega-Fassade").

The productive implementation lives in
``agentkit.backend.state_backend.store.telemetry_read_repository`` and is wired in
the composition root, mirroring the proven ``StoryReadPort`` pattern
(``story.repository`` Protocol + ``state_backend.store.story_read_repository``
adapter, AG3-126).

Fail-closed contract: a read against a missing event table propagates the
underlying backend error; a legitimately-empty project returns an empty list
exactly as the state-backend loader defines it — a missing backend is NEVER
masked by a silent empty-OK result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.backend.control_plane.records import TakeoverApprovalRecord
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

__all__ = ["ProjectTelemetryEventSource"]


@runtime_checkable
class ProjectTelemetryEventSource(Protocol):
    """Read-side source for project-scoped execution events.

    The single sanctioned telemetry-event read edge: every project-scoped
    execution-event read (backing the SSE live view) flows through this
    published Protocol. Implementations are the only place that knows the
    ``state_backend.store`` project execution-event loader.
    """

    def events_for_project(
        self,
        project_key: str,
        *,
        limit: int = 200,
    ) -> list[ExecutionEventRecord]:
        """Return recent execution events for one project (empty list when none)."""
        ...

    def pending_takeover_approvals_for_project(
        self,
        project_key: str | None,
    ) -> tuple[TakeoverApprovalRecord, ...]:
        """Return pending approvals for one project or all projects."""
        ...

    def takeover_approval_events_global(
        self,
        *,
        limit: int = 200,
    ) -> list[ExecutionEventRecord]:
        """Return recent cross-project takeover approval change events."""
        ...
