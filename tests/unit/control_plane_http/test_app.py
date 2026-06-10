"""Unit tests for control_plane_http.app (AG3-090).

Covers:
  - AC1: compat re-export resolves to same class as new namespace owner
  - AC2: project-scoped URL routing for stories, dashboard, story-runs, closure
  - AC2: legacy /v1/stories... bare paths return 404 (no implicit bypass)
  - AC3: tenant-scope middleware integration (unknown project -> 404, archived -> 403)
  - AC3: story mutations through project-scoped path blocked by archived-project scope
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
from agentkit.control_plane_http.app import (
    ControlPlaneApplication,
    ControlPlaneApplicationRoutes,
    HttpResponse,
)
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
        routes=ControlPlaneApplicationRoutes(
            project_routes=_FakeProjectRoutes(),  # type: ignore[arg-type]
            story_routes=_FakeStoryContextRoutes(),  # type: ignore[arg-type]
            concept_routes=_FakeConceptRoutes(),  # type: ignore[arg-type]
            hub_routes=_FakeHubRoutes(),  # type: ignore[arg-type]
            planning_routes=_FakePlanningRoutes(),  # type: ignore[arg-type]
            telemetry_routes=telemetry_routes or _FakeTelemetryRoutes(),  # type: ignore[arg-type]
            auth_routes=_FakeAuthRoutes(),  # type: ignore[arg-type]
            pipeline_engine_routes=pipeline_engine_routes or PipelineEngineRoutes(service_available=True),
            verify_system_routes=VerifySystemRoutes(service_available=True),
            governance_routes=GovernanceRoutes(service_available=True),
            closure_routes=ClosureRoutes(service_available=True),
            artifacts_routes=ArtifactsRoutes(service_available=True),
            kpi_analytics_routes=KpiAnalyticsRoutes(service_available=True),
            failure_corpus_routes=FailureCorpusRoutes(service_available=True),
            requirements_coverage_routes=RequirementsCoverageRoutes(service_available=True),
        ),
        tenant_scope_middleware=tenant_scope or _NoopTenantScope(),  # type: ignore[arg-type]
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


# ---------------------------------------------------------------------------
# Helpers for story-routing tests that need a real StoryContextRoutes
# ---------------------------------------------------------------------------


def _make_story_routes() -> object:
    """Build a real StoryContextRoutes backed by in-memory repos."""
    from agentkit.project_management.entities import Project, ProjectConfiguration
    from agentkit.story_context_manager.http.routes import StoryContextRoutes
    from agentkit.story_context_manager.idempotency import InMemoryIdempotencyKeyRepository
    from agentkit.story_context_manager.service import StoryService
    from agentkit.story_context_manager.story_repository import InMemoryStoryRepository

    class _InMemProjectRepo:
        def __init__(self) -> None:
            self._p: dict[str, Project] = {
                "proj-a": Project(
                    key="proj-a",
                    name="Proj A",
                    story_id_prefix="PA",
                    configuration=ProjectConfiguration(
                        repo_url="",
                        default_branch="main",
                        default_worker_count=1,
                        repositories=["proj-a"],
                    ),
                ),
            }

        def get(self, key: str) -> Project | None:
            return self._p.get(key)

        def list(self, *, include_archived: bool = False) -> list[Project]:
            return list(self._p.values())

        def save(self, project: Project) -> None:
            self._p[project.key] = project

    svc = StoryService(
        story_repository=InMemoryStoryRepository(),
        project_repository=_InMemProjectRepo(),  # type: ignore[arg-type]
        idempotency_repository=InMemoryIdempotencyKeyRepository(),
    )
    return StoryContextRoutes(story_service=svc)


def _make_app_with_real_story_routes(
    *,
    tenant_scope: object | None = None,
) -> ControlPlaneApplication:
    """ControlPlaneApplication with real StoryContextRoutes for integration checks."""
    from agentkit.artifacts.http.routes import ArtifactsRoutes
    from agentkit.closure.http.routes import ClosureRoutes
    from agentkit.failure_corpus.http.routes import FailureCorpusRoutes
    from agentkit.governance.http.routes import GovernanceRoutes
    from agentkit.kpi_analytics.http.routes import KpiAnalyticsRoutes
    from agentkit.requirements_coverage.http.routes import RequirementsCoverageRoutes
    from agentkit.verify_system.http.routes import VerifySystemRoutes

    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            project_routes=_FakeProjectRoutes(),  # type: ignore[arg-type]
            story_routes=_make_story_routes(),  # type: ignore[arg-type]
            concept_routes=_FakeConceptRoutes(),  # type: ignore[arg-type]
            hub_routes=_FakeHubRoutes(),  # type: ignore[arg-type]
            planning_routes=_FakePlanningRoutes(),  # type: ignore[arg-type]
            telemetry_routes=_FakeTelemetryRoutes(),  # type: ignore[arg-type]
            auth_routes=_FakeAuthRoutes(),  # type: ignore[arg-type]
            pipeline_engine_routes=PipelineEngineRoutes(service_available=True),
            verify_system_routes=VerifySystemRoutes(service_available=True),
            governance_routes=GovernanceRoutes(service_available=True),
            closure_routes=ClosureRoutes(service_available=True),
            artifacts_routes=ArtifactsRoutes(service_available=True),
            kpi_analytics_routes=KpiAnalyticsRoutes(service_available=True),
            failure_corpus_routes=FailureCorpusRoutes(service_available=True),
            requirements_coverage_routes=RequirementsCoverageRoutes(service_available=True),
        ),
        tenant_scope_middleware=tenant_scope or _NoopTenantScope(),  # type: ignore[arg-type]
    )


def _create_story_via_app(app: ControlPlaneApplication, project_key: str = "proj-a") -> str:
    """Create a story via the project-scoped POST and return its story_id."""
    resp = app.handle_request(
        method="POST",
        path=f"/v1/projects/{project_key}/stories",
        body=json.dumps({
            "op_id": "op-setup-001",
            "project_key": project_key,
            "title": "Test story",
            "type": "implementation",
            "repos": [project_key],
        }).encode(),
    )
    assert resp.status_code == 201, f"Story creation failed: {resp.status_code} {resp.body}"
    return str(json.loads(resp.body)["story_id"])


# ---------------------------------------------------------------------------
# AC2 — legacy /v1/stories bare paths must return 404
# ---------------------------------------------------------------------------


def test_legacy_get_stories_collection_returns_404() -> None:
    """GET /v1/stories?project_key=... (legacy) is no longer routed; must 404 (AC2)."""
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/stories?project_key=proj-a",
        body=b"",
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


def test_legacy_get_story_detail_returns_404() -> None:
    """GET /v1/stories/{id} (legacy bare path) must 404 (AC2)."""
    app = _make_app()
    response = app.handle_request(
        method="GET",
        path="/v1/stories/AG3-100",
        body=b"",
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


def test_legacy_post_story_approve_returns_404() -> None:
    """POST /v1/stories/{id}/approve (legacy) is no longer routed; must 404 (AC2/AC3)."""
    app = _make_app()
    response = app.handle_request(
        method="POST",
        path="/v1/stories/AG3-100/approve",
        body=json.dumps({"op_id": "op-1"}).encode(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


def test_legacy_post_story_reject_returns_404() -> None:
    """POST /v1/stories/{id}/reject (legacy) is no longer routed; must 404 (AC2/AC3)."""
    app = _make_app()
    response = app.handle_request(
        method="POST",
        path="/v1/stories/AG3-100/reject",
        body=json.dumps({"op_id": "op-1"}).encode(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


def test_legacy_post_story_cancel_returns_404() -> None:
    """POST /v1/stories/{id}/cancel (legacy) is no longer routed; must 404 (AC2/AC3)."""
    app = _make_app()
    response = app.handle_request(
        method="POST",
        path="/v1/stories/AG3-100/cancel",
        body=json.dumps({"op_id": "op-1"}).encode(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


def test_legacy_patch_story_returns_404() -> None:
    """PATCH /v1/stories/{id} (legacy) is no longer routed; must 404 (AC2/AC3)."""
    app = _make_app()
    response = app.handle_request(
        method="PATCH",
        path="/v1/stories/AG3-100",
        body=json.dumps({"op_id": "op-1", "title": "New"}).encode(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


def test_legacy_put_story_field_returns_404() -> None:
    """PUT /v1/stories/{id}/fields/{key} (legacy) is no longer routed; must 404 (AC2/AC3)."""
    app = _make_app()
    response = app.handle_request(
        method="PUT",
        path="/v1/stories/AG3-100/fields/title",
        body=json.dumps({"op_id": "op-1", "value": "New"}).encode(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(response)["error_code"] == "not_found"  # type: ignore[index]


# ---------------------------------------------------------------------------
# AC2 — project-scoped story paths cover all operations
# ---------------------------------------------------------------------------


def test_project_scoped_story_collection_get_resolves() -> None:
    """GET /v1/projects/{key}/stories resolves (tenant-scoped path, no legacy bypass) (AC2)."""
    app = _make_app_with_real_story_routes()

    get_resp = app.handle_request(
        method="GET",
        path="/v1/projects/proj-a/stories",
        body=b"",
    )
    # Route resolves (200 OK with empty list - no stories in the test read-model).
    # Key: this is NOT 404 (route missing) and goes through tenant-scope.
    assert get_resp.status_code == HTTPStatus.OK
    body = _json_body(get_resp)
    assert isinstance(body, dict)
    assert "stories" in body


def test_project_scoped_story_collection_post() -> None:
    """POST /v1/projects/{key}/stories creates a story (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)
    assert story_id.startswith("PA-")


def test_project_scoped_story_detail_get_unknown_returns_404() -> None:
    """GET /v1/projects/{key}/stories/{id} resolves to a story-not-found 404 (AC2).

    The route IS reachable (project-scoped path resolves via tenant-scope) but
    the story itself doesn't exist, so the service returns 404.  This is
    different from a routing-404 (error_code='not_found') — it proves the
    project-scoped path dispatches correctly.
    """
    app = _make_app_with_real_story_routes()

    resp = app.handle_request(
        method="GET",
        path="/v1/projects/proj-a/stories/PA-999",
        body=b"",
    )
    # Story not found in read-model -> story service returns None -> 404 story_not_found.
    # This error_code proves the story route handler ran (not a routing 404).
    assert resp.status_code == HTTPStatus.NOT_FOUND
    assert _json_body(resp)["error_code"] == "story_not_found"  # type: ignore[index]


def test_project_scoped_story_approve_post() -> None:
    """POST /v1/projects/{key}/stories/{id}/approve works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)

    resp = app.handle_request(
        method="POST",
        path=f"/v1/projects/proj-a/stories/{story_id}/approve",
        body=json.dumps({"op_id": "op-approve-1"}).encode(),
    )
    assert resp.status_code == HTTPStatus.OK
    assert _json_body(resp)["status"] == "Approved"  # type: ignore[index]


def test_project_scoped_story_reject_post() -> None:
    """POST /v1/projects/{key}/stories/{id}/reject works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)
    # First approve, then reject
    app.handle_request(
        method="POST",
        path=f"/v1/projects/proj-a/stories/{story_id}/approve",
        body=json.dumps({"op_id": "op-approve-1"}).encode(),
    )
    resp = app.handle_request(
        method="POST",
        path=f"/v1/projects/proj-a/stories/{story_id}/reject",
        body=json.dumps({"op_id": "op-reject-1"}).encode(),
    )
    assert resp.status_code == HTTPStatus.OK
    assert _json_body(resp)["status"] == "Backlog"  # type: ignore[index]


def test_project_scoped_story_cancel_post() -> None:
    """POST /v1/projects/{key}/stories/{id}/cancel works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)

    resp = app.handle_request(
        method="POST",
        path=f"/v1/projects/proj-a/stories/{story_id}/cancel",
        body=json.dumps({"op_id": "op-cancel-1", "reason": "Not needed"}).encode(),
    )
    assert resp.status_code == HTTPStatus.OK
    assert _json_body(resp)["status"] == "Cancelled"  # type: ignore[index]


def test_project_scoped_story_fields_get() -> None:
    """GET /v1/projects/{key}/stories/{id}/fields works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)

    resp = app.handle_request(
        method="GET",
        path=f"/v1/projects/proj-a/stories/{story_id}/fields",
        body=b"",
    )
    assert resp.status_code == HTTPStatus.OK
    body = _json_body(resp)
    assert isinstance(body, dict)
    assert "fields" in body


def test_project_scoped_story_field_key_put() -> None:
    """PUT /v1/projects/{key}/stories/{id}/fields/{fkey} works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)

    resp = app.handle_request(
        method="PUT",
        path=f"/v1/projects/proj-a/stories/{story_id}/fields/title",
        body=json.dumps({"op_id": "op-put-1", "value": "Updated title"}).encode(),
    )
    assert resp.status_code == HTTPStatus.OK
    assert _json_body(resp)["title"] == "Updated title"  # type: ignore[index]


def test_project_scoped_story_patch() -> None:
    """PATCH /v1/projects/{key}/stories/{id} works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    story_id = _create_story_via_app(app)

    resp = app.handle_request(
        method="PATCH",
        path=f"/v1/projects/proj-a/stories/{story_id}",
        body=json.dumps({"op_id": "op-patch-1", "title": "Patched title"}).encode(),
    )
    assert resp.status_code == HTTPStatus.OK
    assert _json_body(resp)["title"] == "Patched title"  # type: ignore[index]


def test_project_scoped_story_search() -> None:
    """GET /v1/projects/{key}/stories/search?q=... works through tenant-scope (AC2)."""
    app = _make_app_with_real_story_routes()
    _create_story_via_app(app)

    resp = app.handle_request(
        method="GET",
        path="/v1/projects/proj-a/stories/search?q=Test",
        body=b"",
    )
    assert resp.status_code == HTTPStatus.OK
    body = _json_body(resp)
    assert isinstance(body, dict)
    stories = body["stories"]
    assert isinstance(stories, list)
    assert len(stories) >= 1


# ---------------------------------------------------------------------------
# AC3 — fail-open hole closed: mutations on archived/unknown project blocked
# ---------------------------------------------------------------------------


def test_story_mutation_on_archived_project_returns_403() -> None:
    """Story POST on archived project is blocked by tenant-scope (AC3 fail-open hole closed)."""
    app = _make_app_with_real_story_routes(tenant_scope=_ArchivedTenantScope())

    response = app.handle_request(
        method="POST",
        path="/v1/projects/archived-proj/stories",
        body=json.dumps({
            "op_id": "op-1",
            "project_key": "archived-proj",
            "title": "Forbidden story",
            "type": "implementation",
            "repos": ["r"],
        }).encode(),
    )
    # Archived project -> tenant-scope blocks mutation -> 403
    assert response.status_code == HTTPStatus.FORBIDDEN
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "forbidden"
    assert _header(response, "X-Correlation-Id") is not None


def test_story_approve_on_archived_project_returns_403() -> None:
    """POST approve on archived project is blocked by tenant-scope (AC3 fail-open hole closed)."""
    app = _make_app_with_real_story_routes(tenant_scope=_ArchivedTenantScope())

    response = app.handle_request(
        method="POST",
        path="/v1/projects/archived-proj/stories/PA-001/approve",
        body=json.dumps({"op_id": "op-1"}).encode(),
    )
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert _json_body(response)["error_code"] == "forbidden"  # type: ignore[index]


def test_story_mutation_on_unknown_project_returns_404() -> None:
    """Story mutation on unknown project is blocked by tenant-scope (AC3 fail-open hole closed)."""
    app = _make_app_with_real_story_routes(tenant_scope=_RejectingTenantScope())

    response = app.handle_request(
        method="POST",
        path="/v1/projects/no-such-project/stories/PA-001/cancel",
        body=json.dumps({"op_id": "op-1"}).encode(),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    body = _json_body(response)
    assert isinstance(body, dict)
    assert body["error_code"] == "project_not_found"
