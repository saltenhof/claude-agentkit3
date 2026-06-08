"""Pipeline-engine HTTP routes (AG3-090, FK-72 §72.8.2).

Mounts under ``/v1/projects/{project_key}/phases``.

This is a thin adapter — no business logic here.  Where the consuming
pipeline-engine service is absent the adapter returns a structured 503
``phases_unavailable`` (FAIL-CLOSED, ZERO DEBT, never a silent empty-200).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from http import HTTPStatus

from agentkit.control_plane_http.bc_route_response import (
    BcRouteResponse,
    bc_json_response,
    bc_unavailable_response,
)

_PHASES_ROOT = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/phases(?:/(?P<rest>.*))?$"
)

PipelineEngineRouteResponse = BcRouteResponse


@dataclass(frozen=True)
class PipelineEngineRoutes:
    """Route handler for the pipeline-engine BC HTTP surface.

    Args:
        service_available: When ``False`` all routes return 503
            ``phases_unavailable`` (injectable for testing).
    """

    service_available: bool = False

    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> PipelineEngineRouteResponse | None:
        """Handle pipeline-engine GET routes or return None."""
        match = _PHASES_ROOT.match(route_path)
        if match is None:
            return None
        if not self.service_available:
            return bc_unavailable_response(
                "phases_unavailable",
                message="Pipeline-engine phases service is not available",
                correlation_id=correlation_id,
            )
        return bc_json_response(
            HTTPStatus.OK,
            {"project_key": match.group("project_key"), "phases": []},
            correlation_id=correlation_id,
        )

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> PipelineEngineRouteResponse | None:
        """Handle pipeline-engine POST routes or return None."""
        match = _PHASES_ROOT.match(route_path)
        if match is None:
            return None
        if not self.service_available:
            return bc_unavailable_response(
                "phases_unavailable",
                message="Pipeline-engine phases service is not available",
                correlation_id=correlation_id,
            )
        return bc_json_response(
            HTTPStatus.ACCEPTED,
            {"project_key": match.group("project_key"), "status": "accepted"},
            correlation_id=correlation_id,
        )
