"""KPI analytics HTTP routes (AG3-090, FK-72 §72.8.2).

Mounts under ``/v1/projects/{project_key}/kpi`` (singular, PO decision
2026-06-08, deckungsgleich mit AG3-084 / AG3-094 / FK-63).

Endpoints:
  GET /v1/projects/{key}/kpi/stories    -- story KPI dimension
  GET /v1/projects/{key}/kpi/guards     -- guards KPI dimension
  GET /v1/projects/{key}/kpi/pools      -- pools KPI dimension
  GET /v1/projects/{key}/kpi/pipeline   -- pipeline KPI dimension
  GET /v1/projects/{key}/kpi/corpus     -- failure-corpus KPI dimension

KPI endpoint business logic stays AG3-084.  This module mounts the root and
makes the endpoints reachable (ZERO DEBT: backend absent -> 503, never 501).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import Literal

from agentkit.control_plane.models import (
    BcRouteResponse,
    bc_json_response,
    bc_unavailable_response,
)

_KPI_ROOT = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/kpi"
    r"(?:/(?P<dimension>stories|guards|pools|pipeline|corpus))?/?$"
)

KpiDimension = Literal["stories", "guards", "pools", "pipeline", "corpus"]
KpiAnalyticsRouteResponse = BcRouteResponse


@dataclass(frozen=True)
class KpiAnalyticsRoutes:
    """Route handler for the kpi-analytics BC HTTP surface.

    Args:
        service_available: When ``False`` all routes return 503
            ``kpi_unavailable`` (backend KPI logic is AG3-084).
    """

    service_available: bool = False

    def handle_get(
        self,
        route_path: str,
        _query: dict[str, list[str]],
        correlation_id: str,
    ) -> KpiAnalyticsRouteResponse | None:
        """Handle KPI GET routes or return None.

        Matches ``/v1/projects/{key}/kpi`` (root) and the five dimension
        sub-resources (``/kpi/{stories|guards|pools|pipeline|corpus}``).
        """
        match = _KPI_ROOT.match(route_path)
        if match is None:
            return None
        if not self.service_available:
            return bc_unavailable_response(
                "kpi_unavailable",
                message="KPI analytics service is not available (business logic: AG3-084)",
                correlation_id=correlation_id,
            )
        dimension = match.group("dimension")
        project_key = match.group("project_key")
        return bc_json_response(
            HTTPStatus.OK,
            {
                "project_key": project_key,
                "dimension": dimension,
                "data": [],
            },
            correlation_id=correlation_id,
        )

    def handle_post(
        self,
        _route_path: str,
        _payload: object,
        _correlation_id: str,
    ) -> KpiAnalyticsRouteResponse | None:
        """Handle KPI POST routes or return None (KPI is read-only)."""
        # KPI surface is read-only; POST not routed here.
        return None
