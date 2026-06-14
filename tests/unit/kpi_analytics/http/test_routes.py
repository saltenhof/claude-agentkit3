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
    from agentkit.control_plane.models import BcRouteResponse

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


# ---------------------------------------------------------------------------
# AG3-092 — design token route tests (AC3)
# ---------------------------------------------------------------------------


def test_design_tokens_route_returns_200() -> None:
    """AC3: GET /v1/projects/{key}/kpi/design-tokens returns 200."""
    routes = KpiAnalyticsRoutes(service_available=True)
    result = routes.handle_get("/v1/projects/myproj/kpi/design-tokens", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)


def test_design_tokens_route_available_even_when_service_unavailable() -> None:
    """AC3: design-token endpoint is always available (no backend dependency)."""
    routes = KpiAnalyticsRoutes(service_available=False)
    result = routes.handle_get("/v1/projects/myproj/kpi/design-tokens", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)


def test_design_tokens_route_echoes_project_key() -> None:
    """AC3: response includes the project_key from the path."""
    routes = KpiAnalyticsRoutes(service_available=True)
    result = routes.handle_get("/v1/projects/tenant-x/kpi/design-tokens", {}, _CORR)
    assert result is not None
    body = _json(result)
    assert isinstance(body, dict)
    assert body["project_key"] == "tenant-x"


def test_design_tokens_route_contains_all_families() -> None:
    """AC3: response body contains all token families."""
    routes = KpiAnalyticsRoutes(service_available=True)
    result = routes.handle_get("/v1/projects/myproj/kpi/design-tokens", {}, _CORR)
    assert result is not None
    body = _json(result)
    assert isinstance(body, dict)
    assert "colors" in body
    assert "typography" in body
    assert "spacing" in body
    assert "control" in body
    assert "chart" in body


def test_design_tokens_route_body_is_deterministic() -> None:
    """AC3: two calls return identical bodies (deterministic token set)."""
    routes = KpiAnalyticsRoutes()
    r1 = routes.handle_get("/v1/projects/myproj/kpi/design-tokens", {}, _CORR)
    r2 = routes.handle_get("/v1/projects/myproj/kpi/design-tokens", {}, _CORR)
    assert r1 is not None
    assert r2 is not None
    # Bodies must be identical (project_key is the same)
    assert r1.body == r2.body


def test_design_tokens_route_not_claimed_by_dimension_handler() -> None:
    """AC3: design-tokens sub-path is NOT matched by the dimension handler."""
    # The dimension handler only accepts known dimensions (stories|guards|...)
    routes = KpiAnalyticsRoutes(service_available=True)
    # /kpi/design-tokens must return 200 from the token route, not None
    result = routes.handle_get("/v1/projects/myproj/kpi/design-tokens", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)
