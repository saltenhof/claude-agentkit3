"""End-to-end integration test for design token delivery (AG3-092, AC10).

AC10 — HARD CRITERION (user directive 2026-06-11):
  A real consumer request flows through the real ``ControlPlaneApplication``
  / ``ControlPlaneApplicationRoutes`` entry point → real
  ``KpiAnalyticsRoutes._handle_design_tokens`` → real
  ``get_design_system()`` token owner → returns the fully typed token set.

  - No mocking at the owner boundary or the HTTP adapter boundary.
  - Proves the ``NotImplementedError`` stub is replaced (the stub would
    have caused a 500 response here).
  - Proves the token route is reachable through the productive app
    (not just via a hand-constructed ``KpiAnalyticsRoutes`` in unit tests).

The test follows the pattern of ``test_execution_input_app.py`` (AG3-100):
only sanctioned route doubles are injected for unrelated BCs; the REAL
``KpiAnalyticsRoutes`` is used for the design-token assertion.
"""

from __future__ import annotations

import json
from http import HTTPStatus

from agentkit.control_plane_http.app import (
    ControlPlaneApplication,
    ControlPlaneApplicationRoutes,
)
from agentkit.control_plane_http.tenant_scope import TenantScopeMiddleware
from agentkit.kpi_analytics.http.routes import KpiAnalyticsRoutes
from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.project_management.lifecycle import create_project

_PROJECT = "tenant-e2e"
_DESIGN_TOKENS_PATH = f"/v1/projects/{_PROJECT}/kpi/design-tokens"


# ---------------------------------------------------------------------------
# Minimal test double for unrelated BCs (must never claim the token route)
# ---------------------------------------------------------------------------


class _AbstainRoute:
    """Passthrough stub: never claims any route.

    Only the REAL ``KpiAnalyticsRoutes`` may claim the design-token path;
    every other BC route in the app must abstain.
    """

    def handle_get(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None  # type: ignore[return-value]

    def handle_post(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None  # type: ignore[return-value]

    def handle_put(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None  # type: ignore[return-value]

    def handle_patch(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None  # type: ignore[return-value]

    def handle_delete(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None  # type: ignore[return-value]


class _ProjectRepo:
    """Minimal project repository double for TenantScopeMiddleware."""

    def get(self, key: str) -> Project | None:
        if key != _PROJECT:
            return None
        return create_project(
            _PROJECT,
            "E2E Tenant",
            "AK3",
            ProjectConfiguration(
                repo_url="",
                default_branch="main",
                default_worker_count=1,
                repositories=["repo-e2e"],
            ),
            repositories=["repo-e2e"],
        )


# ---------------------------------------------------------------------------
# App factory — real KpiAnalyticsRoutes, abstain stubs everywhere else
# ---------------------------------------------------------------------------


def _build_app() -> ControlPlaneApplication:
    """Wire the productive app with the REAL KpiAnalyticsRoutes."""
    project_repo = _ProjectRepo()
    fake = _AbstainRoute()
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=fake,  # type: ignore[arg-type]
            story_routes=fake,  # type: ignore[arg-type]
            concept_routes=fake,  # type: ignore[arg-type]
            hub_routes=fake,  # type: ignore[arg-type]
            planning_routes=fake,  # type: ignore[arg-type]
            telemetry_routes=fake,  # type: ignore[arg-type]
            auth_routes=fake,  # type: ignore[arg-type]
            pipeline_engine_routes=fake,  # type: ignore[arg-type]
            verify_system_routes=fake,  # type: ignore[arg-type]
            governance_routes=fake,  # type: ignore[arg-type]
            closure_routes=fake,  # type: ignore[arg-type]
            artifacts_routes=fake,  # type: ignore[arg-type]
            kpi_analytics_routes=KpiAnalyticsRoutes(),  # ← REAL, not a fake
            failure_corpus_routes=fake,  # type: ignore[arg-type]
            requirements_coverage_routes=fake,  # type: ignore[arg-type]
        ),
        tenant_scope_middleware=TenantScopeMiddleware(repository=project_repo),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# AC10 — E2E tests through the real control_plane_http boundary
# ---------------------------------------------------------------------------


def test_ac10_design_tokens_reachable_through_full_app() -> None:
    """AC10: GET /v1/projects/{key}/kpi/design-tokens returns 200 through the real app.

    Proves:
    1. The route is registered in the productive ControlPlaneApplication.
    2. The REAL KpiAnalyticsRoutes is wired (not a stub).
    3. The REAL get_design_system() owner is called (not NotImplementedError).
    """
    app = _build_app()
    response = app.handle_request(
        method="GET",
        path=_DESIGN_TOKENS_PATH,
        body=b"",
    )
    assert response.status_code == int(HTTPStatus.OK), (
        f"Expected 200 from design-token route, got {response.status_code}. "
        "This may mean the NotImplementedError stub is still in place or the "
        "route is not wired through the productive app."
    )


def test_ac10_response_contains_typed_token_families() -> None:
    """AC10: E2E response body contains all typed token families from the real owner."""
    app = _build_app()
    response = app.handle_request(
        method="GET",
        path=_DESIGN_TOKENS_PATH,
        body=b"",
    )
    assert response.status_code == int(HTTPStatus.OK)
    body: dict[str, object] = json.loads(response.body)

    # All token families must be present
    for family in ("colors", "typography", "spacing", "control", "chart"):
        assert family in body, f"Token family {family!r} missing from E2E response"
        assert body[family], f"Token family {family!r} is empty in E2E response"


def test_ac10_token_values_match_real_owner() -> None:
    """AC10: E2E token values come from the REAL DesignSystem owner (not stubs).

    Spot-checks specific known values against the prototype CSS to ensure
    the real owner was consulted (not a NotImplemented / empty fallback).
    """
    app = _build_app()
    response = app.handle_request(
        method="GET",
        path=_DESIGN_TOKENS_PATH,
        body=b"",
    )
    body: dict[str, object] = json.loads(response.body)

    # Spot-check known color values from the prototype CSS
    colors = body.get("colors", {})
    assert isinstance(colors, dict)
    neutral = colors.get("neutral", {})
    assert isinstance(neutral, dict)
    assert neutral.get("bg") == "#111214", (
        "bg color does not match owner — stub may still be in place"
    )
    assert neutral.get("text") == "#f0f0f0"

    status = colors.get("status", {})
    assert isinstance(status, dict)
    assert status.get("success") == "#74d17f"
    assert status.get("done") == "#82c4ff"

    # Spot-check chart series
    chart = body.get("chart", {})
    assert isinstance(chart, dict)
    series = chart.get("series", {})
    assert isinstance(series, dict)
    assert series.get("series_0") == "#48e7ff", "First chart series color missing"


def test_ac10_project_key_echoed_in_response() -> None:
    """AC10: the project_key from the URL is echoed in the token response."""
    app = _build_app()
    response = app.handle_request(
        method="GET",
        path=_DESIGN_TOKENS_PATH,
        body=b"",
    )
    body: dict[str, object] = json.loads(response.body)
    assert body.get("project_key") == _PROJECT


def test_ac10_status_family_complete_in_e2e_response() -> None:
    """AC10/AC7: E2E response includes the complete status color family."""
    app = _build_app()
    response = app.handle_request(
        method="GET",
        path=_DESIGN_TOKENS_PATH,
        body=b"",
    )
    body: dict[str, object] = json.loads(response.body)
    status = body.get("colors", {}).get("status", {})  # type: ignore[union-attr]
    assert isinstance(status, dict)

    required_keys = {
        "success", "warning", "danger", "info",           # severity
        "done", "cancelled",                                # terminal states
        "status_backlog", "status_approved",               # workflow
        "status_in_progress", "status_done",
        "status_cancelled",
    }
    for key in required_keys:
        assert key in status, f"Status key {key!r} missing from E2E response"


def test_ac10_not_implemented_error_is_gone() -> None:
    """AC10: the NotImplementedError stub has been demonstrably replaced.

    The stub would have caused a 500 response. This test verifies we get 200.
    If this test passes, the stub replacement is proven in the full E2E flow.
    """
    app = _build_app()
    response = app.handle_request(
        method="GET",
        path=_DESIGN_TOKENS_PATH,
        body=b"",
    )
    # If the NotImplementedError stub were still present, the app would return 500
    assert response.status_code != 500, (
        "Got 500 — the NotImplementedError stub may still be active"
    )
    assert response.status_code == int(HTTPStatus.OK)
