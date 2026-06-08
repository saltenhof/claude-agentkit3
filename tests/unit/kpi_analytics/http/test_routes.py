"""Unit tests for kpi_analytics.http.routes (AG3-090, AC6).

Verifies:
  - GET /v1/projects/{key}/kpi -> 200 (root) when service_available
  - GET /v1/projects/{key}/kpi/{dim} -> 200 for all 5 dimensions
  - KPI POST is read-only -> always returns None
  - GET -> 503 kpi_unavailable when not service_available
  - Unrelated path -> None
"""

from __future__ import annotations

import json
from http import HTTPStatus

import pytest

from agentkit.kpi_analytics.http.routes import KpiAnalyticsRoutes

_CORR = "test-corr-kpi-001"
_KPI_DIMENSIONS = ("stories", "guards", "pools", "pipeline", "corpus")


def _json(response: object) -> object:
    from agentkit.control_plane_http.bc_route_response import BcRouteResponse

    assert isinstance(response, BcRouteResponse)
    return json.loads(response.body)


def test_get_kpi_root_available_returns_200() -> None:
    routes = KpiAnalyticsRoutes(service_available=True)
    result = routes.handle_get("/v1/projects/myproj/kpi", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["project_key"] == "myproj"


@pytest.mark.parametrize("dimension", _KPI_DIMENSIONS)
def test_get_kpi_dimension_available_returns_200(dimension: str) -> None:
    """PO decision 2026-06-08: singular /kpi root with 5 dimension sub-routes."""
    routes = KpiAnalyticsRoutes(service_available=True)
    result = routes.handle_get(f"/v1/projects/myproj/kpi/{dimension}", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["dimension"] == dimension


def test_kpi_post_is_readonly_returns_none() -> None:
    """KPI surface is read-only; POST must return None (not claimed)."""
    routes = KpiAnalyticsRoutes(service_available=True)
    assert routes.handle_post("/v1/projects/myproj/kpi", {}, _CORR) is None
    assert routes.handle_post("/v1/projects/myproj/kpi/stories", {}, _CORR) is None


def test_get_kpi_unavailable_returns_503() -> None:
    routes = KpiAnalyticsRoutes(service_available=False)
    result = routes.handle_get("/v1/projects/myproj/kpi", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "kpi_unavailable"


def test_unknown_kpi_dimension_returns_none() -> None:
    """Dimension not in the allow-list must not be claimed by this route."""
    routes = KpiAnalyticsRoutes(service_available=True)
    assert routes.handle_get("/v1/projects/myproj/kpi/unknown-dim", {}, _CORR) is None


def test_unrelated_path_returns_none() -> None:
    routes = KpiAnalyticsRoutes(service_available=True)
    assert routes.handle_get("/v1/projects/myproj/phases", {}, _CORR) is None
