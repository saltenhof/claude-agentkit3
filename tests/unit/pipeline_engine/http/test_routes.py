"""Unit tests for pipeline_engine.http.routes (AG3-090, AC4).

Verifies:
  - GET /v1/projects/{key}/phases -> 200 when service_available
  - POST /v1/projects/{key}/phases -> 202 when service_available
  - GET /v1/projects/{key}/phases -> 503 phases_unavailable when not service_available
  - Unrelated path -> None (no 404 fallthrough)
"""

from __future__ import annotations

import json
from http import HTTPStatus

from agentkit.pipeline_engine.http.routes import PipelineEngineRoutes

_CORR = "test-corr-pe-001"


def _json(response: object) -> object:
    from agentkit.control_plane_http.bc_route_response import BcRouteResponse

    assert isinstance(response, BcRouteResponse)
    return json.loads(response.body)


def test_get_phases_available_returns_200() -> None:
    routes = PipelineEngineRoutes(service_available=True)
    result = routes.handle_get("/v1/projects/myproj/phases", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["project_key"] == "myproj"


def test_get_phases_subpath_available_returns_200() -> None:
    routes = PipelineEngineRoutes(service_available=True)
    result = routes.handle_get("/v1/projects/myproj/phases/setup", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)


def test_post_phases_available_returns_202() -> None:
    routes = PipelineEngineRoutes(service_available=True)
    result = routes.handle_post("/v1/projects/myproj/phases", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.ACCEPTED)


def test_get_phases_unavailable_returns_503() -> None:
    """Backend absent -> 503 phases_unavailable, never 501, never silent 200."""
    routes = PipelineEngineRoutes(service_available=False)
    result = routes.handle_get("/v1/projects/myproj/phases", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "phases_unavailable"


def test_post_phases_unavailable_returns_503() -> None:
    routes = PipelineEngineRoutes(service_available=False)
    result = routes.handle_post("/v1/projects/myproj/phases", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)


def test_unrelated_path_returns_none() -> None:
    """Routes must NOT claim ownership of unrelated paths."""
    routes = PipelineEngineRoutes(service_available=True)
    assert routes.handle_get("/v1/projects/myproj/stories", {}, _CORR) is None
    assert routes.handle_post("/v1/projects/myproj/stories", {}, _CORR) is None
