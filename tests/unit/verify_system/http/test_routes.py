"""Unit tests for verify_system.http.routes (AG3-090, AC5).

Verifies:
  - GET /v1/projects/{key}/verify -> 200 when service_available
  - POST /v1/projects/{key}/verify -> 202 when service_available
  - GET -> 503 verify_unavailable when not service_available
  - Unrelated path -> None
"""

from __future__ import annotations

import json
from http import HTTPStatus

from agentkit.backend.verify_system.http.routes import VerifySystemRoutes

_CORR = "test-corr-vs-001"


def _json(response: object) -> object:
    from agentkit.backend.control_plane.models import BcRouteResponse

    assert isinstance(response, BcRouteResponse)
    return json.loads(response.body)


def test_get_verify_available_returns_200() -> None:
    routes = VerifySystemRoutes(service_available=True)
    result = routes.handle_get("/v1/projects/myproj/verify", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["project_key"] == "myproj"


def test_post_verify_available_returns_202() -> None:
    routes = VerifySystemRoutes(service_available=True)
    result = routes.handle_post("/v1/projects/myproj/verify", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.ACCEPTED)


def test_get_verify_unavailable_returns_503() -> None:
    routes = VerifySystemRoutes(service_available=False)
    result = routes.handle_get("/v1/projects/myproj/verify", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "verify_unavailable"


def test_unrelated_path_returns_none() -> None:
    routes = VerifySystemRoutes(service_available=True)
    assert routes.handle_get("/v1/projects/myproj/phases", {}, _CORR) is None
    assert routes.handle_post("/v1/projects/myproj/phases", {}, _CORR) is None
