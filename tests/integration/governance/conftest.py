"""Loopback governance client for the guard-dispatch integration tests (AG3-129).

These suites exercise guard *logic* (block/allow/emit-content), not the Dev<->Core
transport. AG3-129 moved the guard-counter, worker-health and telemetry hook
writes onto REST; the transport itself is covered end-to-end by the real
plain-HTTP + Postgres tests under ``tests/integration/governance_hooks``.

To keep these guard-logic suites fast and focused (no docker, no server) WITHOUT
reintroducing a direct-DB path in the production code, an autouse fixture routes
the runner's REST client factory to a ``LoopbackGovernanceClient``: it invokes the
REAL server-side control-plane services in-process against the test's local state
backend. It is a real-component loopback (not a mock) -- the same services the
HTTP handler calls, minus the socket hop.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.guard_counter import (
    ControlPlaneGuardCounterService,
)
from agentkit.backend.control_plane.models import (
    GuardCounterMutationAccepted,
    GuardCounterMutationRequest,
    PermissionLeaseView,
    PermissionRequestOpenRequest,
    PermissionRequestsResponse,
    PermissionRequestView,
    TelemetryEventAccepted,
    TelemetryEventIngestRequest,
    TelemetryEventQueryResponse,
    WorkerHealthSaveAccepted,
    WorkerHealthStateResponse,
)
from agentkit.backend.control_plane.telemetry import execution_event_to_wire
from agentkit.backend.control_plane.worker_health import (
    ControlPlaneWorkerHealthService,
)
from agentkit.backend.state_backend.store.guard_counter_repository import (
    StateBackendGuardCounterRepository,
)
from agentkit.backend.state_backend.store.story_read_repository import (
    StateBackendStoryReadRepository,
)
from agentkit.backend.state_backend.store.worker_health_repository import (
    StateBackendWorkerHealthRepository,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    append_execution_event,
    load_execution_events,
)
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


class LoopbackGovernanceClient:
    """In-process stand-in for ``GovernanceEdgeClient`` (real services, no HTTP)."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._permission_requests: list[PermissionRequestView] = []

    def open_permission_request(
        self, request: PermissionRequestOpenRequest
    ) -> PermissionRequestView:
        """Exercise the runner contract without a productive local writer."""
        now = datetime.now(UTC)
        view = PermissionRequestView(
            **request.model_dump(exclude={"operation", "ttl_seconds"}),
            status="pending",
            requested_at=now,
            expires_at=now + timedelta(seconds=request.ttl_seconds),
        )
        self._permission_requests.append(view)
        return view

    def read_permission_requests(
        self, *, project_key: str, story_id: str, run_id: str
    ) -> PermissionRequestsResponse:
        """Return only the requested canonical scope in the loopback."""
        return PermissionRequestsResponse(
            requests=tuple(
                item
                for item in self._permission_requests
                if (item.project_key, item.story_id, item.run_id)
                == (project_key, story_id, run_id)
            )
        )

    def consume_permission_lease(self, lease_id: str) -> PermissionLeaseView:
        """Reject absent loopback leases; productive consumption is PG-tested."""
        raise RuntimeError(f"permission lease {lease_id!r} is unavailable")

    def mutate_guard_counter(
        self, request: GuardCounterMutationRequest
    ) -> GuardCounterMutationAccepted:
        return ControlPlaneGuardCounterService(
            store_factory=lambda: StateBackendGuardCounterRepository(
                self._project_root
            ),
        ).apply(request)

    def load_worker_health(
        self, *, story_id: str, worker_id: str
    ) -> WorkerHealthStateResponse:
        return ControlPlaneWorkerHealthService(
            repository_factory=lambda: StateBackendWorkerHealthRepository(
                self._project_root
            )
        ).load(story_id=story_id, worker_id=worker_id)

    def save_worker_health(
        self, state: Mapping[str, object]
    ) -> WorkerHealthSaveAccepted:
        return ControlPlaneWorkerHealthService(
            repository_factory=lambda: StateBackendWorkerHealthRepository(
                self._project_root
            )
        ).save(dict(state))

    def emit_telemetry_event(
        self, request: TelemetryEventIngestRequest
    ) -> TelemetryEventAccepted:
        story_dir = self._project_root / "stories" / request.story_id
        event_id = request.event_id or f"evt-{uuid.uuid4().hex}"
        append_execution_event(
            story_dir,
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

    def query_telemetry_events(
        self,
        *,
        project_key: str,
        story_id: str,
        event_type: str | None = None,
    ) -> TelemetryEventQueryResponse:
        story_dir = self._project_root / "stories" / story_id
        records = load_execution_events(
            story_dir,
            project_key=project_key,
            story_id=story_id,
            event_type=event_type,
        )
        return TelemetryEventQueryResponse(
            events=[execution_event_to_wire(record) for record in records]
        )

    def get_story_type(self, *, project_key: str, story_id: str) -> str | None:
        # Mirrors the real GET /v1/projects/{key}/stories/{id} read (StoryReadPort),
        # against the test's local backend.
        context = StateBackendStoryReadRepository(self._project_root).load_story_context(
            project_key, story_id
        )
        if context is None:
            return None
        story_type = context.story_type
        return getattr(story_type, "value", story_type)


@pytest.fixture(autouse=True)
def _loopback_governance_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route the shared governance REST client seam to the loopback client."""
    from agentkit.backend.governance import rest_edge

    monkeypatch.setattr(
        rest_edge,
        "governance_edge_client",
        lambda project_root: LoopbackGovernanceClient(project_root),
    )
