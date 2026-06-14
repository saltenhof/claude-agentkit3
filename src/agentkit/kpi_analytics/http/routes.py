"""KPI analytics HTTP routes (AG3-090, FK-72 §72.8.2).

Mounts under ``/v1/projects/{project_key}/kpi`` (singular, PO decision
2026-06-08, deckungsgleich mit AG3-084 / AG3-094 / FK-63).

Endpoints:
  GET /v1/projects/{key}/kpi/stories       -- story KPI dimension
  GET /v1/projects/{key}/kpi/guards        -- guards KPI dimension
  GET /v1/projects/{key}/kpi/pools         -- pools KPI dimension
  GET /v1/projects/{key}/kpi/pipeline      -- pipeline KPI dimension
  GET /v1/projects/{key}/kpi/corpus        -- failure-corpus KPI dimension
  GET /v1/projects/{key}/kpi/design-tokens -- FK-64 design token set (AG3-092)

KPI endpoint business logic stays AG3-084.  Design-token delivery (AG3-092)
is a thin static adapter: it serializes the deterministic ``DesignSystem``
owner (no business logic in the HTTP layer, FK-64 §64.2).
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
from agentkit.kpi_analytics.design_system import get_design_system

# Route for KPI dimensions (stories / guards / pools / pipeline / corpus)
_KPI_DIMENSION_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/kpi"
    r"(?:/(?P<dimension>stories|guards|pools|pipeline|corpus))?/?$"
)

# Static design-token route (AG3-092, FK-64 §64.2)
_KPI_DESIGN_TOKENS_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/kpi/design-tokens/?$"
)

KpiDimension = Literal["stories", "guards", "pools", "pipeline", "corpus"]
KpiAnalyticsRouteResponse = BcRouteResponse


@dataclass(frozen=True)
class KpiAnalyticsRoutes:
    """Route handler for the kpi-analytics BC HTTP surface.

    AG3-092 extends AG3-090 with a static design-token read endpoint (thin
    adapter, FK-64 §64.2: no business logic in the HTTP layer).

    Args:
        service_available: When ``False`` the KPI data routes return 503
            ``kpi_unavailable`` (business logic is AG3-084).  The design-token
            route is *always* available regardless of this flag (it has no
            backend dependency).
    """

    service_available: bool = False

    def handle_get(
        self,
        route_path: str,
        _query: dict[str, list[str]],
        correlation_id: str,
    ) -> KpiAnalyticsRouteResponse | None:
        """Handle KPI GET routes or return None.

        Matches the design-token route first (FK-64 §64.2 static read), then
        the five KPI dimension sub-resources.
        """
        # Design-token route: always available, no service_available guard.
        dt_match = _KPI_DESIGN_TOKENS_PATH.match(route_path)
        if dt_match is not None:
            return self._handle_design_tokens(
                dt_match.group("project_key"), correlation_id
            )

        dim_match = _KPI_DIMENSION_PATH.match(route_path)
        if dim_match is None:
            return None
        if not self.service_available:
            return bc_unavailable_response(
                "kpi_unavailable",
                message="KPI analytics service is not available (business logic: AG3-084)",
                correlation_id=correlation_id,
            )
        dimension = dim_match.group("dimension")
        project_key = dim_match.group("project_key")
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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _handle_design_tokens(
        project_key: str,
        correlation_id: str,
    ) -> BcRouteResponse:
        """Thin static adapter: serialize the deterministic DesignSystem owner.

        FK-64 §64.2: no dynamic computation; this is a pure serialization of
        the typed token owner.  The ``project_key`` is echoed in the response
        for consumer orientation but does NOT affect the token values (tokens
        are global, not project-scoped).
        """
        ds = get_design_system()
        payload: dict[str, object] = {
            "project_key": project_key,
            "colors": ds.colors.model_dump(mode="json"),
            "typography": ds.typography.model_dump(mode="json"),
            "spacing": ds.spacing.model_dump(mode="json"),
            "control": ds.control.model_dump(mode="json"),
            "chart": ds.chart.model_dump(mode="json"),
        }
        return bc_json_response(HTTPStatus.OK, payload, correlation_id=correlation_id)
