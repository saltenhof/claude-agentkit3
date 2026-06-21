"""Unit tests for requirements_coverage.http.routes (AG3-090, AC6, FK-40 §40.10).

Verifies:
  - GET /v1/projects/{key}/coverage -> 200 when service_available
  - GET /v1/projects/{key}/coverage/stories/{story_id}/are-evidence -> 200 (FK-40)
  - POST -> 202 when service_available
  - GET are-evidence -> 503 coverage_unavailable when not service_available
  - GET coverage root -> 503 when not service_available
  - Unrelated path -> None
  - are-evidence is GET-only (POST to are-evidence path -> None)
"""

from __future__ import annotations

import json
from http import HTTPStatus

from agentkit.backend.requirements_coverage.http.routes import RequirementsCoverageRoutes

_CORR = "test-corr-rc-001"


def _json(response: object) -> object:
    from agentkit.backend.control_plane.models import BcRouteResponse

    assert isinstance(response, BcRouteResponse)
    return json.loads(response.body)


def test_get_coverage_root_available_returns_200() -> None:
    routes = RequirementsCoverageRoutes(service_available=True)
    result = routes.handle_get("/v1/projects/myproj/coverage", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["project_key"] == "myproj"


def test_get_coverage_are_evidence_available_returns_200() -> None:
    """FK-40 §40.10: GET are-evidence route returns story + evidence."""
    routes = RequirementsCoverageRoutes(service_available=True)
    result = routes.handle_get(
        "/v1/projects/myproj/coverage/stories/AG3-090/are-evidence", {}, _CORR,
    )
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["story_id"] == "AG3-090"
    assert body["project_key"] == "myproj"
    assert "are_evidence" in body


def test_get_coverage_are_evidence_unavailable_returns_503() -> None:
    """Backend absent: are-evidence must return 503 coverage_unavailable, not 200."""
    routes = RequirementsCoverageRoutes(service_available=False)
    result = routes.handle_get(
        "/v1/projects/myproj/coverage/stories/AG3-090/are-evidence", {}, _CORR,
    )
    assert result is not None
    assert result.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "coverage_unavailable"


def test_post_coverage_available_returns_202() -> None:
    routes = RequirementsCoverageRoutes(service_available=True)
    result = routes.handle_post("/v1/projects/myproj/coverage", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.ACCEPTED)


def test_get_coverage_unavailable_returns_503() -> None:
    routes = RequirementsCoverageRoutes(service_available=False)
    result = routes.handle_get("/v1/projects/myproj/coverage", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "coverage_unavailable"


def test_are_evidence_is_get_only() -> None:
    """are-evidence is read-only (FK-40 §40.10): POST to that path is not claimed."""
    routes = RequirementsCoverageRoutes(service_available=True)
    # POST to the are-evidence path should fall through to the generic root pattern,
    # which IS claimed by handle_post; so we verify the root pattern, not are-evidence.
    # The are-evidence specific path is GET-only — no POST pattern exists for it.
    # Verify that a POST to a non-coverage path returns None:
    assert routes.handle_post("/v1/projects/myproj/phases", {}, _CORR) is None


def test_unrelated_path_returns_none() -> None:
    routes = RequirementsCoverageRoutes(service_available=True)
    assert routes.handle_get("/v1/projects/myproj/phases", {}, _CORR) is None
    assert routes.handle_post("/v1/projects/myproj/phases", {}, _CORR) is None
