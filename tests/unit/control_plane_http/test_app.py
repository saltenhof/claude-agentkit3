"""Unit tests for control_plane_http.app (AG3-090).

Covers:
  - AC1: compat re-export resolves to same class as new namespace owner
  - AC2: project-scoped URL routing for stories, dashboard, story-runs, closure
  - AC3: tenant-scope middleware integration (unknown project -> 404, archived -> 403)
  - AC7: X-Correlation-Id and typed ApiErrorResponse on errors
  - AC8: SSE path (/v1/projects/{key}/events) passes through unmodified
  - 503 unavailable for BC with absent backend
"""

from __future__ import annotations

import json
from http import HTTPStatus

# AC1: compat re-export must resolve to the SAME class
from agentkit.control_plane.http import ControlPlaneApplication as CompatCPA
from agentkit.control_plane.http import HttpResponse as CompatHttpResponse

# AC1: canonical namespace is owner
from agentkit.control_plane_http.app import ControlPlaneApplication, HttpResponse
from agentkit.pipeline_engine.http.routes import PipelineEngineRoutes
from agentkit.telemetry.http.routes import TelemetryRouteResponse

# ---------------------------------------------------------------------------
# AC1 — compat re-export identity
# ---------------------------------------------------------------------------


def test_compat_reexport_is_same_class() -> None:
    """control_plane.http is a compat re-export; the class must be identical."""
    assert ControlPlaneApplication is CompatCPA
    assert HttpResponse is CompatHttpResponse


# ---------------------------------------------------------------------------
# Fakes / stubs
# ---------------------------------------------------------------------------


class _NoopTenantScope:
    """Passthrough stub: every project is valid, no project archived."""

    def validate(self, *, method: str, route_path: str, correlation_id: str) -> None:
        return None


class _RejectingTenantScope:
    """Always rejects as unknown project (404)."""

    def validate(
        self, *, method: str, route_path: str, correlation_id: str
    ) -> HttpResponse:
        body = json.dumps({
            "error_code": "project_not_found",
            "error": "Project not found",
            "correlation_id": correlation_id,
        }).encode()
        return HttpResponse(
            status_code=int(HTTPStatus.NOT_FOUND),
            body=body,
            headers=(("X-Correlation-Id", correlation_id),),
        )


class _ArchivedTenantScope:
    """Rejects mutations (archived project -> 403); passes GET."""

    def validate(
        self, *, method: str, route_path: str, correlation_id: str
    ) -> HttpResponse | None:
        mutation_methods = {"POST", "PUT", "PATCH", "DELETE"}
        if method in mutation_methods:
            body = json.dumps({
                "error_code": "forbidden",
                "error": "Project is archived; mutations are not allowed",
                "correlation_id": correlation_id,
            }).encode()
            return HttpResponse(
                status_code=int(HTTPStatus.FORBIDDEN),
                body=body,
                headers=(("X-Correlation-Id", correlation_id),),
            )
        return None


class _FakeStoryContextRoutes:
    """Minimal stub for StoryContextRoutes used in routing tests."""

    def handle_get(
        self,
        route_path: str,
        correlation_id: str,
        query: dict[str, list[str]] | None = None,
    ) -> None:
        return None

    def handle_post(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None

    def handle_patch(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None

    def handle_put(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None


class _FakeProjectRoutes:
    """Minimal stub for ProjectManagementRoutes."""

    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> None:
        return None

    def handle_post(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None

    def handle_patch(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None

    def handle_put(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None


class _FakeConceptRoutes:
    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> None:
        return None


class _FakeHubRoutes:
    def handle_get(
        self, route_path: str, query: dict[str, list[str]], correlation_id: str
    ) -> None:
        return None

    def handle_post(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None


class _FakePlanningRoutes:
    def handle_get(self, route_path: str, correlation_id: str) -> None:
        return None

    def handle_post(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None

    def handle_put(
        self, route_path: str, payload: object, correlation_id: str
    ) -> None:
        return None

    def handle_delete(self, route_path: str, correlation_id: str) -> None:
        return None


class _FakeTelemetryRoutes:
    """Stub that claims /v1/projects/{key}/events but returns nothing else."""

    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> TelemetryRouteResponse | None:
        import re

        m = re.match(r"^/v1/projects/(?P<project_key>[^/]+)/events$", route_path)
        if m is None:
            return None
        return TelemetryRouteResponse(
            status_code=200,
            body=b"",
            headers=(("Content-Type", "text/event-stream"),),
        )


class _FakeAuthRoutes:
    def handle_get(self, route_path: str, correlation_id: str) -> None:
        return None

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
        request_headers: object = None,
    ) -> None:
        return None

    def handle_delete(
        self, route_path: str, query: dict[str, list[str]], correlation_id: str
    ) -> None:
        return None


def _make_app(
    *,
    tenant_scope: object | None = None,
    pipeline_engine_routes: PipelineEngineRoutes | None = None,
    telemetry_routes: object | None = None,
) -> ControlPlaneApplication:
    """Build a minimal ControlPlaneApplication wired with all fakes."""
    from agentkit.artifacts.http.routes import ArtifactsRoutes
    from agentkit.closure.http.routes import ClosureRoutes
    from agentkit.failure_corpus.http.routes import FailureCorpusRoutes
    from agentkit.governance.http.routes import GovernanceRoutes
    from agentkit.kpi_analytics.http.routes import KpiAnalyticsRoutes
    from agentkit.requirements_coverage.http.routes import RequirementsCoverageRoutes
    from agentkit.verify_system.http.routes import VerifySystemRoutes

    return ControlPlaneApplication(
        project_routes=_FakeProjectRoutes(),  # type: ignore[arg-type]
        story_routes=_FakeStoryContextRoutes(),  # type: ignore[arg-type]
        concept_routes=_FakeConceptRoutes(),  # type: ignore[arg-type]
        hub_routes=_FakeHubRoutes(),  # type: ignore[arg-type]
        planning_routes=_FakePlanningRoutes(),  # type: ignore[arg-type]
        telemetry_routes=telemetry_routes or _FakeTelemetryRoutes(),  # type: ignore[arg-type]
        auth_routes=_FakeAuthRoutes(),  # type: ignore[arg-type]
        tenant_scope_middleware=tenant_scope or _NoopTenantScope(),  # type: ignore[arg-type]
        pipeline_engine_routes=pipeline_engine_routes or PipelineEngineRoutes(service_available=True),
        verify_system_routes=VerifySystemRoutes(service_available=True),
        governance_routes=GovernanceRoutes(service_available=True),
        closure_routes=ClosureRoutes(service_available=True),
        artifacts_routes=ArtifactsRoutes(service_available=True),
        kpi_analytics_routes=KpiAnalyticsRoutes(service_available=True),
        failure_corpus_routes=FailureCorpusRoutes(service_available=True),
        requirements_coverage_routes=RequirementsCoverageRoutes(service_available=True),
    )


def _json_body(response: HttpResponse) -> object:
    return json.loads(response.body)


def _header(response: HttpResponse, name: str) -> str | None:
    for k, v in response.headers:
        if k.lower() == name.lower():
            return v
    return None


# ---------------------------------------------------------------------------
# AC7 — X-Correlation-Id and error_code on errors
# ---------------------------------------------------------------------------


def test_404_carries_correlation_id_and_error_code() -> None:
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/unknown-endpoint-xyz",
        body=b"",
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "not_found"
    assert "correlation_id" in body
    assert _header(response, "X-Correlation-Id") is not None


def test_correlation_id_reflected_from_request_header() -> None:
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/phases",
        body=b"",
        request_headers={"X-Correlation-Id": "custom-corr-99"},
    )
    assert _header(response, "X-Correlation-Id") == "custom-corr-99"


# ---------------------------------------------------------------------------
# AC2 — project-scoped URL routing
# ---------------------------------------------------------------------------


def test_get_project_scoped_phases_returns_200() -> None:
    """GET /v1/projects/{key}/phases hits PipelineEngineRoutes (AC2, AC4)."""
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/phases",
        body=b"",
    )
    assert response.status_code == HTTPStatus.OK
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["project_key"] == "myproj"


def test_get_project_scoped_verify_returns_200() -> None:
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/verify",
        body=b"",
    )
    assert response.status_code == HTTPStatus.OK


def test_get_project_scoped_governance_returns_200() -> None:
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/governance",
        body=b"",
    )
    assert response.status_code == HTTPStatus.OK


def test_get_project_scoped_closure_returns_200() -> None:
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/closure",
        body=b"",
    )
    assert response.status_code == HTTPStatus.OK


def test_get_project_scoped_artifacts_returns_200() -> None:
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/artifacts",
        body=b"",
    )
    assert response.status_code == HTTPStatus.OK


def test_get_project_scoped_kpi_returns_200() -> None:
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/kpi",
        body=b"",
    )
    assert response.status_code == HTTPStatus.OK


def test_get_project_scoped_kpi_dimension_returns_200() -> None:
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/kpi/stories",
        body=b"",
    )
    assert response.status_code == HTTPStatus.OK


def test_get_project_scoped_failure_corpus_returns_200() -> None:
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/failure-corpus",
        body=b"",
    )
    assert response.status_code == HTTPStatus.OK


def test_get_project_scoped_coverage_returns_200() -> None:
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/coverage",
        body=b"",
    )
    assert response.status_code == HTTPStatus.OK


def test_get_project_scoped_coverage_are_evidence_returns_200() -> None:
    """GET /v1/projects/{key}/coverage/stories/{story_id}/are-evidence (FK-40)."""
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/coverage/stories/AG3-001/are-evidence",
        body=b"",
    )
    assert response.status_code == HTTPStatus.OK
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["story_id"] == "AG3-001"


# ---------------------------------------------------------------------------
# AC3 — tenant-scope middleware: unknown project -> 404
# ---------------------------------------------------------------------------


def test_unknown_project_returns_404() -> None:
    """AC3: unknown project_key on a project-scoped path -> 404."""
    app = _make_app(tenant_scope=_RejectingTenantScope())
    response = app.handle_request(
        method="GET",
        path="/v1/projects/no-such-project/phases",
        body=b"",
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "project_not_found"


def test_archived_project_mutation_returns_403() -> None:
    """AC3: archived project + mutation method -> 403/forbidden."""
    app = _make_app(tenant_scope=_ArchivedTenantScope())
    response = app.handle_request(
        method="POST",
        path="/v1/projects/archived-proj/phases",
        body=json.dumps({}).encode(),
    )
    assert response.status_code == HTTPStatus.FORBIDDEN
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "forbidden"


def test_archived_project_get_passes_through() -> None:
    """AC3: archived project + GET -> middleware passes; route handles it."""
    app = _make_app(tenant_scope=_ArchivedTenantScope())
    response = app.handle_request(
        method="GET",
        path="/v1/projects/archived-proj/phases",
        body=b"",
    )
    # Middleware passes (GET), route returns 200 (PipelineEngineRoutes available)
    assert response.status_code == HTTPStatus.OK


# ---------------------------------------------------------------------------
# AC3 — non-project-scoped paths bypass tenant-scope
# ---------------------------------------------------------------------------


def test_healthz_bypasses_tenant_scope() -> None:
    """Non-project path /healthz is not subject to tenant-scope."""
    app = _make_app(tenant_scope=_RejectingTenantScope())
    response = app.handle_request(method="GET", path="/healthz", body=b"")
    assert response.status_code == HTTPStatus.OK


# ---------------------------------------------------------------------------
# AC8 — SSE compat: /v1/projects/{key}/events must pass unchanged
# ---------------------------------------------------------------------------


def test_sse_path_passes_tenant_scope_and_reaches_telemetry_routes() -> None:
    """AC8: SSE /v1/projects/{key}/events goes through tenant-scope and hits TelemetryRoutes."""
    app = _make_app(tenant_scope=_NoopTenantScope())
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/events",
        body=b"",
    )
    # TelemetryRoutes stub returns 200 with Content-Type: text/event-stream
    assert response.status_code == HTTPStatus.OK
    assert _header(response, "Content-Type") == "text/event-stream"


def test_sse_path_with_unknown_project_returns_404() -> None:
    """AC8: unknown project_key for SSE path -> 404 from tenant-scope."""
    app = _make_app(tenant_scope=_RejectingTenantScope())
    response = app.handle_request(
        method="GET",
        path="/v1/projects/no-such/events",
        body=b"",
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "project_not_found"


# ---------------------------------------------------------------------------
# 503 unavailable — BC with absent backend
# ---------------------------------------------------------------------------


def test_bc_route_absent_backend_returns_503() -> None:
    """service_available=False -> 503 phases_unavailable (not silent 200, not 501)."""
    app = _make_app(
        pipeline_engine_routes=PipelineEngineRoutes(service_available=False),
    )
    response = app.handle_request(
        method="GET",
        path="/v1/projects/myproj/phases",
        body=b"",
    )
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "phases_unavailable"
