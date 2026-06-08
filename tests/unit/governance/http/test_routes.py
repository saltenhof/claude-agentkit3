"""Unit tests for governance.http.routes (AG3-090, AC5).

Verifies:
  - GET /v1/projects/{key}/governance -> 200 when service_available
  - POST -> 202 when service_available
  - GET -> 503 governance_unavailable when not service_available
  - Unrelated path -> None
"""

from __future__ import annotations

import json
from http import HTTPStatus

from agentkit.governance.http.routes import GovernanceRoutes

_CORR = "test-corr-gov-001"


def _json(response: object) -> object:
    from agentkit.control_plane_http.bc_route_response import BcRouteResponse

    assert isinstance(response, BcRouteResponse)
    return json.loads(response.body)


def test_get_governance_available_returns_200() -> None:
    routes = GovernanceRoutes(service_available=True)
    result = routes.handle_get("/v1/projects/myproj/governance", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["project_key"] == "myproj"


def test_post_governance_available_returns_202() -> None:
    routes = GovernanceRoutes(service_available=True)
    result = routes.handle_post("/v1/projects/myproj/governance", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.ACCEPTED)


def test_get_governance_unavailable_returns_503() -> None:
    routes = GovernanceRoutes(service_available=False)
    result = routes.handle_get("/v1/projects/myproj/governance", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "governance_unavailable"


def test_unrelated_path_returns_none() -> None:
    routes = GovernanceRoutes(service_available=True)
    assert routes.handle_get("/v1/projects/myproj/phases", {}, _CORR) is None
    assert routes.handle_post("/v1/projects/myproj/phases", {}, _CORR) is None
