"""Governance HTTP routes (AG3-090, FK-72 §72.8.2).

Mounts under ``/v1/projects/{project_key}/governance``.

Thin adapter.  Backend absent -> 503 ``governance_unavailable``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from http import HTTPStatus

from agentkit.backend.control_plane.models import (
    BcRouteResponse,
    bc_json_response,
    bc_unavailable_response,
)

_GOVERNANCE_ROOT = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/governance(?:/(?P<rest>.*))?$"
)

GovernanceRouteResponse = BcRouteResponse


@dataclass(frozen=True)
class GovernanceRoutes:
    """Route handler for the governance BC HTTP surface.

    Args:
        service_available: When ``False`` all routes return 503.
    """

    service_available: bool = False

    def handle_get(
        self,
        route_path: str,
        _query: dict[str, list[str]],
        correlation_id: str,
    ) -> GovernanceRouteResponse | None:
        """Handle governance GET routes or return None."""
        match = _GOVERNANCE_ROOT.match(route_path)
        if match is None:
            return None
        if not self.service_available:
            return bc_unavailable_response(
                "governance_unavailable",
                message="Governance service is not available",
                correlation_id=correlation_id,
            )
        return bc_json_response(
            HTTPStatus.OK,
            {"project_key": match.group("project_key"), "status": "ok"},
            correlation_id=correlation_id,
        )

    def handle_post(
        self,
        route_path: str,
        _payload: object,
        correlation_id: str,
    ) -> GovernanceRouteResponse | None:
        """Handle governance POST routes or return None."""
        match = _GOVERNANCE_ROOT.match(route_path)
        if match is None:
            return None
        if not self.service_available:
            return bc_unavailable_response(
                "governance_unavailable",
                message="Governance service is not available",
                correlation_id=correlation_id,
            )
        return bc_json_response(
            HTTPStatus.ACCEPTED,
            {"project_key": match.group("project_key"), "status": "accepted"},
            correlation_id=correlation_id,
        )
