"""Hook-side REST client for governance state mediation (AG3-129).

FK-10 §10.1.0 I1/I3: the short-lived hook process is a REST *requester* at the
core, never a direct-DB writer. This thin client rides the SAME
``HttpsJsonTransport`` the official :class:`ProjectEdgeClient` uses (SINGLE SOURCE
OF TRUTH -- no second HTTP stack) and mediates the three canonical hook state
operations that previously opened PostgreSQL directly:

* guard-invocation counter record / housekeeping (FK-61 §61.4.3);
* worker-health read / write (FK-30 §30.10);
* execution-telemetry emit / query (FK-30 §30.3 / FK-10 §10.3.2).

The client carries NO database DSN and never imports ``psycopg``; its only
configuration is the control-plane base URL from
``.agentkit/config/control-plane.json`` (the same source as
:func:`build_project_edge_client`).
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.parse
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import (
    GuardCounterMutationAccepted,
    GuardCounterMutationRequest,
    PermissionLeaseConsumeRequest,
    PermissionLeaseGrantRequest,
    PermissionLeaseView,
    PermissionRequestOpenRequest,
    PermissionRequestResolveRequest,
    PermissionRequestsResponse,
    PermissionRequestView,
    TelemetryEventAccepted,
    TelemetryEventIngestRequest,
    TelemetryEventQueryResponse,
    WorkerHealthSaveAccepted,
    WorkerHealthStateResponse,
)
from agentkit.backend.exceptions import ControlPlaneApiError
from agentkit.harness_client.projectedge.client import HttpsJsonTransport

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from agentkit.harness_client.projectedge.client import ControlPlaneTransport
    from agentkit.harness_client.projectedge.permission_projection import LocalPermissionStateProjection

_GUARD_COUNTER_PATH = "/v1/governance/guard-counters"
_WORKER_HEALTH_PATH = "/v1/governance/worker-health"
_TELEMETRY_EVENTS_PATH = "/v1/telemetry/events"
_PERMISSION_REQUESTS_PATH = "/v1/governance/permission-requests"
_PERMISSION_LEASES_PATH = "/v1/governance/permission-leases"
_PROJECT_API_TOKEN_ENV = "AGENTKIT_PROJECT_API_TOKEN"
#: Error code the core returns when a story detail read finds no record.
_STORY_NOT_FOUND_CODE = "story_not_found"


class GovernanceEdgeClient:
    """Thin REST client for the hook's canonical governance state operations."""

    def __init__(
        self, *, transport: ControlPlaneTransport,
        permission_projection: LocalPermissionStateProjection | None = None,
    ) -> None:
        """Bind the client to a control-plane JSON transport.

        Args:
            transport: The shared control-plane transport (``HttpsJsonTransport``
                in production). Reusing the one transport keeps a single HTTP
                stack across every Dev->Core call (AC6).
        """
        self._transport = transport
        self._permission_projection = permission_projection

    # ------------------------------------------------------------------
    # Guard-invocation counter (FK-61 §61.4.3) -- non-blocking volume KPI.
    # ------------------------------------------------------------------

    def mutate_guard_counter(
        self, request: GuardCounterMutationRequest
    ) -> GuardCounterMutationAccepted:
        """Record a guard invocation or run the housekeeping sweep via REST.

        Args:
            request: The typed guard-counter mutation (``record`` or
                ``housekeeping``).

        Returns:
            The accepted server result (with the drained-row count).
        """
        data = self._transport.send(
            method="POST",
            path=_GUARD_COUNTER_PATH,
            payload=request.model_dump(mode="json"),
        )
        data.pop("correlation_id", None)
        return GuardCounterMutationAccepted.model_validate(data)

    def open_permission_request(
        self, request: PermissionRequestOpenRequest
    ) -> PermissionRequestView:
        """Open one canonical permission request through the backend."""
        data = self._transport.send(
            method="POST", path=_PERMISSION_REQUESTS_PATH,
            payload=request.model_dump(mode="json"),
        )
        data.pop("correlation_id", None)
        response = PermissionRequestView.model_validate(data)
        self.read_permission_requests(
            project_key=response.project_key, story_id=response.story_id,
            run_id=response.run_id,
        )
        return response

    def read_permission_requests(
        self, *, project_key: str, story_id: str, run_id: str
    ) -> PermissionRequestsResponse:
        """Read the hook token's run-scoped canonical permission requests."""
        query = urllib.parse.urlencode(
            {"project_key": project_key, "story_id": story_id, "run_id": run_id}
        )
        data = self._transport.send(
            method="GET", path=f"{_PERMISSION_REQUESTS_PATH}?{query}",
        )
        data.pop("correlation_id", None)
        response = PermissionRequestsResponse.model_validate(data)
        if self._permission_projection is not None:
            open_ids = tuple(
                item.request_id for item in response.requests if item.status == "pending"
            )
            self._permission_projection.write_requests(
                project_key, story_id, run_id, open_ids
            )
        return response

    def consume_permission_lease(self, lease_id: str) -> PermissionLeaseView:
        """Consume one use of a canonical permission lease."""
        request = PermissionLeaseConsumeRequest(lease_id=lease_id)
        data = self._transport.send(
            method="POST", path=_PERMISSION_LEASES_PATH,
            payload=request.model_dump(mode="json"),
        )
        data.pop("correlation_id", None)
        return PermissionLeaseView.model_validate(data)

    def resolve_permission_request(
        self, request: PermissionRequestResolveRequest
    ) -> PermissionRequestView:
        """Resolve a canonical request through a strategist-bound transport."""
        data = self._transport.send(
            method="POST",
            path=_PERMISSION_REQUESTS_PATH,
            payload=request.model_dump(mode="json"),
        )
        data.pop("correlation_id", None)
        return PermissionRequestView.model_validate(data)

    def grant_permission_lease(
        self, request: PermissionLeaseGrantRequest
    ) -> PermissionLeaseView:
        """Grant a canonical lease through a strategist-bound transport."""
        data = self._transport.send(
            method="POST",
            path=_PERMISSION_LEASES_PATH,
            payload=request.model_dump(mode="json"),
        )
        data.pop("correlation_id", None)
        return PermissionLeaseView.model_validate(data)

    # ------------------------------------------------------------------
    # Worker-health (FK-30 §30.10) -- fail-closed gate operation.
    # ------------------------------------------------------------------

    def load_worker_health(
        self, *, story_id: str, worker_id: str
    ) -> WorkerHealthStateResponse:
        """Read the canonical worker-health state for one scope via REST.

        Args:
            story_id: The story the health state belongs to.
            worker_id: The worker whose health state to read.

        Returns:
            The server-mediated worker-health read result (``state`` is ``None``
            when no row exists).
        """
        query = urllib.parse.urlencode({"story_id": story_id, "worker_id": worker_id})
        data = self._transport.send(
            method="GET",
            path=f"{_WORKER_HEALTH_PATH}?{query}",
        )
        data.pop("correlation_id", None)
        return WorkerHealthStateResponse.model_validate(data)

    def save_worker_health(
        self, state: Mapping[str, object]
    ) -> WorkerHealthSaveAccepted:
        """Write the canonical worker-health state via REST.

        Args:
            state: The ``AgentHealthState`` wire object (already ``model_dump``ed
                by the caller, which owns the model type).

        Returns:
            The accepted server result.
        """
        data = self._transport.send(
            method="POST",
            path=_WORKER_HEALTH_PATH,
            payload=dict(state),
        )
        data.pop("correlation_id", None)
        return WorkerHealthSaveAccepted.model_validate(data)

    # ------------------------------------------------------------------
    # Telemetry (FK-30 §30.3) -- non-blocking emit, server-mediated query.
    # ------------------------------------------------------------------

    def emit_telemetry_event(
        self, request: TelemetryEventIngestRequest
    ) -> TelemetryEventAccepted:
        """Emit one canonical telemetry event via the existing ingest endpoint.

        Args:
            request: The canonical telemetry ingest request.

        Returns:
            The accepted server result (with the minted ``event_id``).
        """
        data = self._transport.send(
            method="POST",
            path=_TELEMETRY_EVENTS_PATH,
            payload=request.model_dump(mode="json"),
        )
        data.pop("correlation_id", None)
        return TelemetryEventAccepted.model_validate(data)

    # ------------------------------------------------------------------
    # Story-type read (FK-24 §24.3.2) -- fail-closed governance read.
    # ------------------------------------------------------------------

    def get_story_type(self, *, project_key: str, story_id: str) -> str | None:
        """Read a story's canonical type via the existing story detail endpoint.

        Reuses ``GET /v1/projects/{project_key}/stories/{story_id}`` (the
        StoryReadPort surface) so the hook resolves the story type via REST
        instead of opening PostgreSQL (FK-10 §10.1.0 I1).

        Args:
            project_key: The owning project key.
            story_id: The canonical story display id.

        Returns:
            The story-type string, or ``None`` when the core reports no such
            story (missing record). A transport / core fault PROPAGATES so the
            caller can fail closed (UNRESOLVED), never a silent story type.
        """
        project_segment = urllib.parse.quote(project_key, safe="")
        story_segment = urllib.parse.quote(story_id, safe="")
        try:
            data = self._transport.send(
                method="GET",
                path=f"/v1/projects/{project_segment}/stories/{story_segment}",
            )
        except ControlPlaneApiError as exc:
            if exc.error_code == _STORY_NOT_FOUND_CODE:
                return None
            raise
        story_type = data.get("story_type")
        return story_type if isinstance(story_type, str) and story_type else None

    def query_telemetry_events(
        self,
        *,
        project_key: str,
        story_id: str,
        event_type: str | None = None,
    ) -> TelemetryEventQueryResponse:
        """Read canonical execution events for one scope via REST.

        Args:
            project_key: The project scope to read.
            story_id: The story scope to read.
            event_type: Optional canonical event-type filter.

        Returns:
            The server-mediated telemetry read result.
        """
        params: dict[str, str] = {"project_key": project_key, "story_id": story_id}
        if event_type is not None:
            params["event_type"] = event_type
        query = urllib.parse.urlencode(params)
        data = self._transport.send(
            method="GET",
            path=f"{_TELEMETRY_EVENTS_PATH}?{query}",
        )
        data.pop("correlation_id", None)
        return TelemetryEventQueryResponse.model_validate(data)


def build_governance_edge_client(project_root: Path) -> GovernanceEdgeClient:
    """Construct a governance edge client from local control-plane config.

    Mirrors :func:`build_project_edge_client`: the base URL and optional CA file
    are read from ``.agentkit/config/control-plane.json``. No database DSN is
    read (FK-10 §10.1.0 I1); the hook holds no PostgreSQL credentials.

    Args:
        project_root: The project root carrying the local control-plane config.

    Returns:
        A configured :class:`GovernanceEdgeClient`.
    """
    from agentkit.backend.config.loader import load_project_config
    from agentkit.harness_client.projectedge.permission_projection import (
        LocalPermissionStateProjection,
    )
    from agentkit.harness_client.projectedge.runtime import (
        _read_bound_skill_bundle_version,
    )

    config = json.loads(
        (
            project_root / ".agentkit" / "config" / "control-plane.json"
        ).read_text(encoding="utf-8"),
    )
    cafile = config.get("ca_file")
    ssl_context = ssl.create_default_context(cafile=cafile) if cafile else None
    return GovernanceEdgeClient(
        transport=HttpsJsonTransport(
            base_url=str(config["base_url"]),
            ssl_context=ssl_context,
            skill_bundle_version=_read_bound_skill_bundle_version(project_root),
            bearer_token=os.environ.get(_PROJECT_API_TOKEN_ENV),
            project_key=load_project_config(project_root).project_key,
        ),
        permission_projection=LocalPermissionStateProjection(project_root),
    )


__all__ = ["GovernanceEdgeClient", "build_governance_edge_client"]
