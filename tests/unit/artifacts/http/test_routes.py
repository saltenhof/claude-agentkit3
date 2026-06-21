"""Unit tests for artifacts.http.routes (AG3-090, AC6).

Verifies:
  - GET /v1/projects/{key}/artifacts -> 200 when service_available
  - POST -> 202 when service_available
  - GET -> 503 artifacts_unavailable when not service_available
  - Unrelated path -> None
"""

from __future__ import annotations

import json
from http import HTTPStatus

from agentkit.backend.artifacts.http.routes import ArtifactsRoutes

_CORR = "test-corr-art-001"


def _json(response: object) -> object:
    from agentkit.backend.control_plane.models import BcRouteResponse

    assert isinstance(response, BcRouteResponse)
    return json.loads(response.body)


def test_get_artifacts_available_returns_200() -> None:
    routes = ArtifactsRoutes(service_available=True)
    result = routes.handle_get("/v1/projects/myproj/artifacts", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["project_key"] == "myproj"


def test_post_artifacts_available_returns_202() -> None:
    routes = ArtifactsRoutes(service_available=True)
    result = routes.handle_post("/v1/projects/myproj/artifacts", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.ACCEPTED)


def test_get_artifacts_unavailable_returns_503() -> None:
    routes = ArtifactsRoutes(service_available=False)
    result = routes.handle_get("/v1/projects/myproj/artifacts", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "artifacts_unavailable"


def test_unrelated_path_returns_none() -> None:
    routes = ArtifactsRoutes(service_available=True)
    assert routes.handle_get("/v1/projects/myproj/phases", {}, _CORR) is None
    assert routes.handle_post("/v1/projects/myproj/phases", {}, _CORR) is None
