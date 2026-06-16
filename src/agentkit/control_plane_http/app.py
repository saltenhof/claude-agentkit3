"""HTTPS transport and routing for the AgentKit control plane (FK-72 §72.8.2).

This is the canonical implementation (moved from ``control_plane/http.py``
by AG3-090).  ``agentkit.control_plane.http`` holds a compat re-export only.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPSServer
from typing import TYPE_CHECKING, cast
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from agentkit.auth.middleware import AuthMiddlewareResponse
from agentkit.control_plane.models import (
    ApiErrorResponse,
    ClosureCompleteRequest,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
    TelemetryEventIngestRequest,
)
from agentkit.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.control_plane.telemetry import ControlPlaneTelemetryService
from agentkit.control_plane_http.tenant_scope import TenantScopeMiddleware
from agentkit.exceptions import ConfigError
from agentkit.kpi_analytics.dashboard import DashboardService
from agentkit.story.service import StoryService

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from agentkit.artifacts.http.routes import ArtifactsRoutes
    from agentkit.auth.http.routes import AuthRouteResponse, AuthRoutes
    from agentkit.auth.middleware import AuthMiddleware
    from agentkit.closure.http.routes import ClosureRoutes
    from agentkit.concept_catalog.http.routes import ConceptCatalogRoutes, ConceptRouteResponse
    from agentkit.execution_planning.http.routes import ExecutionPlanningRouteResponse, ExecutionPlanningRoutes
    from agentkit.failure_corpus.http.routes import FailureCorpusRoutes
    from agentkit.governance.http.routes import GovernanceRoutes
    from agentkit.kpi_analytics.http.routes import KpiAnalyticsRoutes
    from agentkit.multi_llm_hub.http.routes import MultiLlmHubRouteResponse, MultiLlmHubRoutes
    from agentkit.pipeline_engine.http.routes import PipelineEngineRoutes
    from agentkit.project_management.http.routes import ProjectManagementRoutes, ProjectRouteResponse
    from agentkit.project_management.read_model_routes import ReadModelRoutes
    from agentkit.requirements_coverage.http.routes import RequirementsCoverageRoutes
    from agentkit.story_context_manager.http.routes import StoryContextRoutes, StoryRouteResponse
    from agentkit.task_management.http.routes import TaskManagementRoutes
    from agentkit.telemetry.http.routes import TelemetryRouteResponse, TelemetryRoutes
    from agentkit.verify_system.http.routes import VerifySystemRoutes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path patterns — project-scoped (FK-72 §72.8.1)
# ---------------------------------------------------------------------------

# Legacy non-project paths (kept for non-project-scoped resources only):
_OPERATION_PATH_PATTERN = re.compile(
    r"^/v1/project-edge/operations/(?P<op_id>[^/]+)$",
)

# Project-scoped paths under /v1/projects/{project_key}/<bc>/...
_PROJECT_SCOPED_PREFIX = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/(?P<rest>.+)$",
)

# story-runs (project-scoped by project_key in path since AG3-090):
_PROJECT_PHASE_PATH_PATTERN = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/story-runs/(?P<run_id>[^/]+)"
    r"/phases/(?P<phase>[^/]+)/(?P<action>start|complete|fail)$",
)
_PROJECT_CLOSURE_PATH_PATTERN = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/story-runs/(?P<run_id>[^/]+)/closure/complete$",
)
# Project-scoped story paths:
_PROJECT_STORIES_COLLECTION = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories$",
)
_PROJECT_STORY_DETAIL = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)$",
)
_PROJECT_STORY_APPROVE = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)/approve$",
)
_PROJECT_STORY_REJECT = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)/reject$",
)
_PROJECT_STORY_CANCEL = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)/cancel$",
)
_PROJECT_STORY_FIELDS = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)/fields$",
)
_PROJECT_STORY_FIELD_KEY = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)"
    r"/fields/(?P<field_key>[^/]+)$",
)
_PROJECT_STORY_SEARCH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/search$",
)
_PROJECT_DASHBOARD_BOARD = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/dashboard/board$",
)
_PROJECT_DASHBOARD_STORY_METRICS = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/dashboard/story-metrics$",
)

_NOT_FOUND_MESSAGE = "Not found"
_CORRELATION_HEADER = "X-Correlation-Id"


# ---------------------------------------------------------------------------
# Default-builder helpers (lazy imports)
# ---------------------------------------------------------------------------


def _build_default_project_routes() -> ProjectManagementRoutes:
    from agentkit.project_management.http.routes import ProjectManagementRoutes
    from agentkit.story_context_manager.service import (
        StoryService as StoryContextStoryService,
    )

    _ctx_service: list[StoryContextStoryService | None] = [None]

    def _repos_in_use_checker(
        project_key: str,
        repos: list[str],
    ) -> list[str]:
        svc = _ctx_service[0]
        if svc is None:
            svc = StoryContextStoryService()
            _ctx_service[0] = svc
        in_use = svc.list_active_repos(project_key)
        return [r for r in repos if r in in_use]

    return ProjectManagementRoutes(repos_in_use_checker=_repos_in_use_checker)


def _build_default_story_routes() -> StoryContextRoutes:
    from agentkit.story_context_manager.http.routes import StoryContextRoutes

    return StoryContextRoutes()


def _build_default_concept_routes() -> ConceptCatalogRoutes:
    from agentkit.concept_catalog.http.routes import ConceptCatalogRoutes

    return ConceptCatalogRoutes()


def _build_default_hub_routes() -> MultiLlmHubRoutes:
    from agentkit.multi_llm_hub.http.routes import MultiLlmHubRoutes

    return MultiLlmHubRoutes()


def _build_default_planning_routes() -> ExecutionPlanningRoutes:
    from agentkit.execution_planning.http.routes import ExecutionPlanningRoutes

    return ExecutionPlanningRoutes()


def _build_default_telemetry_routes() -> TelemetryRoutes:
    from agentkit.telemetry.http.routes import TelemetryRoutes

    return TelemetryRoutes()


def _build_default_auth_routes(auth_middleware: AuthMiddleware | None) -> AuthRoutes:
    from agentkit.auth.http.routes import AuthRoutes

    if auth_middleware is not None:
        return AuthRoutes(
            session_store=auth_middleware.session_store,
            token_repository=auth_middleware.token_repository,
        )
    return AuthRoutes()


def _build_default_pipeline_engine_routes() -> PipelineEngineRoutes:
    from agentkit.pipeline_engine.http.routes import PipelineEngineRoutes

    return PipelineEngineRoutes()


def _build_default_verify_system_routes() -> VerifySystemRoutes:
    from agentkit.verify_system.http.routes import VerifySystemRoutes

    return VerifySystemRoutes()


def _build_default_governance_routes() -> GovernanceRoutes:
    from agentkit.governance.http.routes import GovernanceRoutes

    return GovernanceRoutes()


def _build_default_closure_routes() -> ClosureRoutes:
    from agentkit.closure.http.routes import ClosureRoutes

    return ClosureRoutes()


def _build_default_artifacts_routes() -> ArtifactsRoutes:
    from agentkit.artifacts.http.routes import ArtifactsRoutes

    return ArtifactsRoutes()


def _build_default_kpi_analytics_routes() -> KpiAnalyticsRoutes:
    """Build the default KpiAnalyticsRoutes backed by a real FactStore.

    Wires ``StateBackendFactRepository`` (the production SQLite/Postgres
    adapter) into a real ``FactStore`` and ``KpiAnalytics`` so that the five
    KPI dimension endpoints read live data from the fact tables.  This is the
    composition root for the kpi_analytics BC (AC1/AC3 — real FactStore reads,
    not a stub).

    The ``KpiCatalog`` and ``FactStore`` are the minimal dependencies required
    for ``KpiAnalytics``; the optional ``RefreshWorker`` is omitted here
    (refresh is triggered by the closure pipeline, not by the HTTP read path).
    """
    from agentkit.kpi_analytics.catalog import KpiCatalog
    from agentkit.kpi_analytics.fact_store.store import FactStore
    from agentkit.kpi_analytics.http.routes import KpiAnalyticsRoutes
    from agentkit.kpi_analytics.top import KpiAnalytics
    from agentkit.state_backend.store.fact_repository import StateBackendFactRepository

    fact_repo = StateBackendFactRepository()
    fact_store = FactStore(fact_repo)
    kpi_analytics = KpiAnalytics(catalog=KpiCatalog(), fact_store=fact_store)
    return KpiAnalyticsRoutes(kpi_analytics=kpi_analytics)


def _build_default_task_management_routes() -> TaskManagementRoutes:
    """Build the default task-management BC route handler backed by real storage."""
    import os
    import pathlib

    from agentkit.state_backend.store.projection_repositories import (
        build_projection_repositories,
    )
    from agentkit.task_management.http.routes import TaskManagementRoutes
    from agentkit.task_management.service import TaskManagement
    from agentkit.telemetry.projection_accessor import ProjectionAccessor

    store_dir = pathlib.Path(os.environ.get("AGENTKIT_STORE_DIR", "."))
    repos = build_projection_repositories(store_dir)
    accessor = ProjectionAccessor(repos)
    service = TaskManagement(accessor)
    return TaskManagementRoutes(task_management=service)


def _build_default_failure_corpus_routes() -> FailureCorpusRoutes:
    from agentkit.failure_corpus.http.routes import FailureCorpusRoutes

    return FailureCorpusRoutes()


def _build_default_requirements_coverage_routes() -> RequirementsCoverageRoutes:
    from agentkit.requirements_coverage.http.routes import RequirementsCoverageRoutes

    return RequirementsCoverageRoutes()


def _build_default_read_model_routes() -> ReadModelRoutes:
    from agentkit.project_management.read_model_routes import ReadModelRoutes
    from agentkit.state_backend.store.parallelization_config_repository import (
        StateBackendParallelizationConfigRepository,
    )
    from agentkit.state_backend.store.project_management_repository import (
        StateBackendProjectRepository,
    )
    from agentkit.state_backend.store.story_are_link_repository import (
        StateBackendStoryAreLinkRepository,
    )
    from agentkit.story_context_manager.service import StoryService as _StoryContextService

    return ReadModelRoutes(
        project_repository=StateBackendProjectRepository(),
        story_service=_StoryContextService(),
        config_repository=StateBackendParallelizationConfigRepository(),
        are_link_repository=StateBackendStoryAreLinkRepository(),
    )


# ---------------------------------------------------------------------------
# AG3-091 read-only 405 guard (module-level — no instance state required)
# ---------------------------------------------------------------------------


def _handle_healthz(method: str, correlation_id: str) -> HttpResponse:
    """Return the /healthz response (200 OK for GET, 405 for anything else)."""
    if method != "GET":
        return _error_response(
            HTTPStatus.METHOD_NOT_ALLOWED,
            error_code="method_not_allowed",
            message="Method not allowed",
            correlation_id=correlation_id,
            headers=(("Allow", "GET"),),
        )
    return _json_response(
        HTTPStatus.OK,
        {"status": "ok"},
        correlation_id=correlation_id,
    )


def _handle_get_operation(
    runtime_service: ControlPlaneRuntimeService,
    op_id: str,
    correlation_id: str,
) -> HttpResponse:
    """Return the project-edge operation status (module-level helper, AG3-105 LOC split)."""
    try:
        result = runtime_service.get_operation(op_id)
    except ConfigError as exc:
        return _backend_requirement_response(
            "project_edge_reconcile_unavailable", exc, correlation_id
        )
    except RuntimeError as exc:
        logger.warning("Project-edge reconcile unavailable: %s", exc)
        return _error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            error_code="project_edge_reconcile_unavailable",
            message=str(exc),
            correlation_id=correlation_id,
        )
    if result is None:
        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="operation_not_found",
            message="Operation not found",
            correlation_id=correlation_id,
        )
    return _json_response(
        HTTPStatus.OK,
        result.model_dump(mode="json"),
        correlation_id=correlation_id,
    )


def _read_only_method_not_allowed(
    read_model_routes: ReadModelRoutes,
    route_path: str,
    correlation_id: str,
) -> HttpResponse | None:
    """Return 405 for a mutation on an AG3-091 read-only path, else None.

    Only called for POST/PUT/PATCH (GET/DELETE return earlier).  Reuses the
    verb-agnostic ``ReadModelRoutes`` 405-matcher (all mutation verbs map to
    the same ``_method_not_allowed_if_matches`` with ``Allow: GET``) so the
    read-only-endpoint decision lives in exactly one place (SSOT).  Running
    this BEFORE ``_decode_json_body`` ensures the 405 fires regardless of the
    request body — an empty or non-JSON body on a read-only path must NOT
    degrade to ``400 invalid_json`` (FAIL-CLOSED, AC1/AC5).
    """
    response = read_model_routes.handle_post(route_path, None, correlation_id)
    if response is not None:
        return _bc_response_to_http_response(response)
    return None


# ---------------------------------------------------------------------------
# HttpResponse
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HttpResponse:
    """Serializable HTTP response."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()
    stream: Iterable[bytes] | None = None


# ---------------------------------------------------------------------------
# ControlPlaneApplicationRoutes — groups all BC-route dependencies (S107)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlPlaneApplicationRoutes:
    """Optional route-bundle for :class:`ControlPlaneApplication`.

    Collects all 15 BC-route and middleware route overrides into a single
    typed object so that the constructor stays within the S107 parameter-count
    limit.  Every field defaults to ``None``; missing entries are filled with
    their respective ``_build_default_*`` helpers at construction time.
    """

    project_routes: ProjectManagementRoutes | None = None
    story_routes: StoryContextRoutes | None = None
    concept_routes: ConceptCatalogRoutes | None = None
    hub_routes: MultiLlmHubRoutes | None = None
    planning_routes: ExecutionPlanningRoutes | None = None
    telemetry_routes: TelemetryRoutes | None = None
    auth_routes: AuthRoutes | None = None
    pipeline_engine_routes: PipelineEngineRoutes | None = None
    verify_system_routes: VerifySystemRoutes | None = None
    governance_routes: GovernanceRoutes | None = None
    closure_routes: ClosureRoutes | None = None
    artifacts_routes: ArtifactsRoutes | None = None
    kpi_analytics_routes: KpiAnalyticsRoutes | None = None
    failure_corpus_routes: FailureCorpusRoutes | None = None
    requirements_coverage_routes: RequirementsCoverageRoutes | None = None
    read_model_routes: ReadModelRoutes | None = None
    task_management_routes: TaskManagementRoutes | None = None


# ---------------------------------------------------------------------------
# ControlPlaneApplication
# ---------------------------------------------------------------------------


class ControlPlaneApplication:
    """Route and validate HTTP requests for the control plane (FK-72 §72.8.2).

    This is the **single** transport/router.  All BC http/ modules register
    here.  Tenant-scope middleware validates ``project_key`` for every
    project-scoped route (AC3).
    """

    def __init__(
        self,
        *,
        routes: ControlPlaneApplicationRoutes | None = None,
        telemetry_service: ControlPlaneTelemetryService | None = None,
        runtime_service: ControlPlaneRuntimeService | None = None,
        story_service: StoryService | None = None,
        dashboard_service: DashboardService | None = None,
        auth_middleware: AuthMiddleware | None = None,
        tenant_scope_middleware: TenantScopeMiddleware | None = None,
    ) -> None:
        r = routes or ControlPlaneApplicationRoutes()
        self._telemetry_service = telemetry_service or ControlPlaneTelemetryService()
        self._runtime_service = runtime_service or ControlPlaneRuntimeService()
        self._story_service = story_service or StoryService()
        if dashboard_service is not None:
            self._dashboard_service = dashboard_service
        else:
            from agentkit.kpi_analytics.fact_store.store import FactStore
            from agentkit.state_backend.store.fact_repository import StateBackendFactRepository

            _fact_store = FactStore(StateBackendFactRepository())
            self._dashboard_service = DashboardService(
                story_service=self._story_service,
                fact_store=_fact_store,
            )
        self._project_routes = r.project_routes or _build_default_project_routes()
        self._story_routes = r.story_routes or _build_default_story_routes()
        self._concept_routes = r.concept_routes or _build_default_concept_routes()
        self._hub_routes = r.hub_routes or _build_default_hub_routes()
        self._planning_routes = r.planning_routes or _build_default_planning_routes()
        self._telemetry_routes = r.telemetry_routes or _build_default_telemetry_routes()
        self._auth_routes = r.auth_routes or _build_default_auth_routes(auth_middleware)
        self._auth_middleware = auth_middleware
        self._tenant_scope = tenant_scope_middleware or TenantScopeMiddleware()
        self._init_bc_routes(r)

    def _init_bc_routes(self, r: ControlPlaneApplicationRoutes) -> None:
        """Initialise the eight AG3-090 BC route handlers (extracted to reduce S3776 complexity)."""
        self._pipeline_engine_routes = (
            r.pipeline_engine_routes or _build_default_pipeline_engine_routes()
        )
        self._verify_system_routes = (
            r.verify_system_routes or _build_default_verify_system_routes()
        )
        self._governance_routes = (
            r.governance_routes or _build_default_governance_routes()
        )
        self._closure_routes = r.closure_routes or _build_default_closure_routes()
        self._artifacts_routes = r.artifacts_routes or _build_default_artifacts_routes()
        self._kpi_analytics_routes = (
            r.kpi_analytics_routes or _build_default_kpi_analytics_routes()
        )
        self._failure_corpus_routes = (
            r.failure_corpus_routes or _build_default_failure_corpus_routes()
        )
        self._requirements_coverage_routes = (
            r.requirements_coverage_routes
            or _build_default_requirements_coverage_routes()
        )
        self._read_model_routes = (
            r.read_model_routes or _build_default_read_model_routes()
        )
        self._task_management_routes = (
            r.task_management_routes or _build_default_task_management_routes()
        )

    def handle_request(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        request_headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Dispatch one HTTP request."""
        correlation_id = _resolve_correlation_id(request_headers)
        split = urlsplit(path)
        route_path = split.path
        query = parse_qs(split.query)

        if route_path == "/healthz":
            return _handle_healthz(method, correlation_id)

        middleware_block = self._run_middleware(
            method, route_path, request_headers, correlation_id
        )
        if middleware_block is not None:
            return middleware_block

        return self._dispatch_method(
            method, route_path, query, body, correlation_id, request_headers
        )

    def _run_middleware(
        self,
        method: str,
        route_path: str,
        request_headers: Mapping[str, str] | None,
        correlation_id: str,
    ) -> HttpResponse | None:
        """Run auth and tenant-scope middleware; return a response to short-circuit or None."""
        if self._auth_middleware is not None:
            auth_result = self._auth_middleware.authorize(
                method=method,
                route_path=route_path,
                request_headers=request_headers,
                correlation_id=correlation_id,
            )
            if isinstance(auth_result, AuthMiddlewareResponse):
                return _auth_middleware_response_to_http_response(auth_result)

        # Tenant-scope middleware: validate project_key for all project-scoped paths.
        # Non-project endpoints (/v1/concepts, /v1/hub, /v1/events/hub, /v1/projects
        # list/create, /healthz, auth, project-edge) bypass tenant-scope.
        if _is_project_scoped_path(route_path):
            tenant_result = self._tenant_scope.validate(
                method=method,
                route_path=route_path,
                correlation_id=correlation_id,
            )
            if isinstance(tenant_result, HttpResponse):
                return tenant_result
        return None

    def _dispatch_method(
        self,
        method: str,
        route_path: str,
        query: dict[str, list[str]],
        body: bytes,
        correlation_id: str,
        request_headers: Mapping[str, str] | None,
    ) -> HttpResponse:
        """Dispatch to the correct HTTP-method handler.

        For mutation methods (POST/PUT/PATCH) the AG3-091 read-only 405 match
        runs BEFORE ``_decode_json_body`` so that a mutation attempt on a
        read-only endpoint returns ``405 method_not_allowed`` regardless of the
        request body (empty, non-JSON, or JSON).  Only when the read-only
        matcher abstains does the body get decoded and dispatched to the normal
        mutation handlers (other BCs' mutation endpoints are unaffected — they
        still decode and dispatch their bodies normally).
        """
        if method == "GET":
            return self._handle_get_request(route_path, query, correlation_id)
        if method == "DELETE":
            return self._handle_delete_request(route_path, correlation_id)
        read_only_block = _read_only_method_not_allowed(
            self._read_model_routes, route_path, correlation_id
        )
        if read_only_block is not None:
            return read_only_block
        payload = _decode_json_body(body, correlation_id)
        if isinstance(payload, HttpResponse):
            return payload
        if method == "PUT":
            return self._handle_put_request(route_path, payload, correlation_id)
        if method == "PATCH":
            return self._handle_patch_request(route_path, payload, correlation_id)
        return self._handle_post_request(
            route_path,
            payload,
            correlation_id,
            request_headers,
        )



    def _handle_get_request(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse:
        # Auth routes (non-project-scoped):
        auth_response = self._auth_routes.handle_get(route_path, correlation_id)
        if auth_response is not None:
            return _auth_response_to_http_response(auth_response)

        # Concept catalog routes (non-project-scoped /v1/concepts):
        concept_response = self._concept_routes.handle_get(
            route_path, query, correlation_id,
        )
        if concept_response is not None:
            return _concept_response_to_http_response(concept_response)

        # Telemetry SSE routes (project-scoped /v1/projects/{key}/events):
        telemetry_response = self._telemetry_routes.handle_get(
            route_path, query, correlation_id,
        )
        if telemetry_response is not None:
            return _telemetry_response_to_http_response(telemetry_response)

        # Multi-LLM hub routes (non-project-scoped /v1/hub):
        hub_response = self._hub_routes.handle_get(route_path, query, correlation_id)
        if hub_response is not None:
            return _hub_response_to_http_response(hub_response)

        # Execution planning routes:
        planning_response = self._planning_routes.handle_get(
            route_path, correlation_id,
        )
        if planning_response is not None:
            return _planning_response_to_http_response(planning_response)

        # Project management routes (/v1/projects, /v1/projects/{key}):
        project_response = self._project_routes.handle_get(
            route_path, query, correlation_id,
        )
        if project_response is not None:
            return _project_response_to_http_response(project_response)

        return self._dispatch_project_scoped_get(route_path, query, correlation_id)

    def _dispatch_project_scoped_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse:
        """Dispatch project-scoped GET routes (stories, dashboard, BC, legacy)."""
        # --- Project-scoped URL convention (FK-72 §72.8.1) ---
        # All story access flows exclusively through /v1/projects/{key}/stories/...
        # so that every story operation passes through TenantScopeMiddleware (AC2/AC3).
        # Legacy bare /v1/stories paths are intentionally NOT delegated here.

        # AG3-091 read-model routes: checked BEFORE story handlers to prevent
        # collisions such as /stories/counters being captured by _PROJECT_STORY_DETAIL.
        rm_response = self._read_model_routes.handle_get(route_path, query, correlation_id)
        if rm_response is not None:
            return _bc_response_to_http_response(rm_response)

        # GET /v1/projects/{key}/stories/search?q=...
        # Must match before /stories/{id} to avoid "search" being treated as story_id.
        story_search_match = _PROJECT_STORY_SEARCH.match(route_path)
        if story_search_match is not None:
            return self._handle_get_story_search(
                story_search_match.group("project_key"), query, correlation_id,
            )

        # GET /v1/projects/{key}/stories (collection)
        stories_match = _PROJECT_STORIES_COLLECTION.match(route_path)
        if stories_match is not None:
            return self._handle_get_stories(stories_match.group("project_key"), correlation_id)

        # GET /v1/projects/{key}/stories/{id}/fields
        # Must match before /stories/{id} (more specific pattern).
        story_fields_match = _PROJECT_STORY_FIELDS.match(route_path)
        if story_fields_match is not None:
            return self._handle_get_story_fields(
                story_fields_match.group("story_id"), correlation_id,
            )

        # GET /v1/projects/{key}/stories/{id}
        story_detail_match = _PROJECT_STORY_DETAIL.match(route_path)
        if story_detail_match is not None:
            return self._handle_get_story(
                story_detail_match.group("story_id"),
                story_detail_match.group("project_key"),
                correlation_id,
            )

        # GET /v1/projects/{key}/dashboard/board
        board_match = _PROJECT_DASHBOARD_BOARD.match(route_path)
        if board_match is not None:
            return self._handle_get_dashboard_board(board_match.group("project_key"), correlation_id)

        # GET /v1/projects/{key}/dashboard/story-metrics
        metrics_match = _PROJECT_DASHBOARD_STORY_METRICS.match(route_path)
        if metrics_match is not None:
            return self._handle_get_dashboard_story_metrics(
                metrics_match.group("project_key"), correlation_id,
            )

        # Eight new BC GET routes (project-scoped):
        bc_get = self._dispatch_new_bc_get(route_path, query, correlation_id)
        if bc_get is not None:
            return bc_get

        # Legacy non-project project-edge operation GET:
        operation_match = _OPERATION_PATH_PATTERN.match(route_path)
        if operation_match is not None:
            return _handle_get_operation(
                self._runtime_service, operation_match.group("op_id"), correlation_id,
            )

        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="not_found",
            message=_NOT_FOUND_MESSAGE,
            correlation_id=correlation_id,
        )

    def _dispatch_new_bc_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse | None:
        """Dispatch GET to the BC http/ modules (AG3-090)."""
        for routes in (
            self._pipeline_engine_routes,
            self._verify_system_routes,
            self._governance_routes,
            self._closure_routes,
            self._artifacts_routes,
            self._kpi_analytics_routes,
            self._failure_corpus_routes,
            self._requirements_coverage_routes,
            self._task_management_routes,
        ):
            response = routes.handle_get(route_path, query, correlation_id)
            if response is not None:
                return _bc_response_to_http_response(response)
        return None

    def _handle_post_request(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
        request_headers: Mapping[str, str] | None,
    ) -> HttpResponse:
        # AG3-091 read-only endpoints already returned 405 in _dispatch_method
        # (before body decode); this handler only sees genuine mutation paths.
        auth_response = self._auth_routes.handle_post(
            route_path, payload, correlation_id, request_headers,
        )
        if auth_response is not None:
            return _auth_response_to_http_response(auth_response)

        project_response = self._project_routes.handle_post(
            route_path, payload, correlation_id,
        )
        if project_response is not None:
            return _project_response_to_http_response(project_response)

        # NOTE: story_routes.handle_post is NOT called with the raw route_path.
        # Story mutations are only reachable via project-scoped paths (AC2/AC3).

        hub_response = self._hub_routes.handle_post(
            route_path, payload, correlation_id,
        )
        if hub_response is not None:
            return _hub_response_to_http_response(hub_response)

        planning_response = self._planning_routes.handle_post(
            route_path, payload, correlation_id,
        )
        if planning_response is not None:
            return _planning_response_to_http_response(planning_response)

        if route_path == "/v1/telemetry/events":
            return self._handle_post_telemetry(payload, correlation_id)
        if route_path == "/v1/project-edge/sync":
            return self._handle_post_project_edge_sync(payload, correlation_id)

        # Project-scoped story mutations:
        story_post = self._dispatch_project_story_post(
            route_path, payload, correlation_id,
        )
        if story_post is not None:
            return story_post

        # Project-scoped phase/closure mutations:
        phase_match = _PROJECT_PHASE_PATH_PATTERN.match(route_path)
        if phase_match is not None:
            return self._handle_post_phase_mutation(
                payload=payload,
                run_id=phase_match.group("run_id"),
                phase=phase_match.group("phase"),
                action=phase_match.group("action"),
                correlation_id=correlation_id,
            )

        closure_match = _PROJECT_CLOSURE_PATH_PATTERN.match(route_path)
        if closure_match is not None:
            return self._handle_post_closure_complete(
                payload=payload,
                run_id=closure_match.group("run_id"),
                correlation_id=correlation_id,
            )

        # Eight new BC POST routes:
        bc_post = self._dispatch_new_bc_post(route_path, payload, correlation_id)
        if bc_post is not None:
            return bc_post

        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="not_found",
            message=_NOT_FOUND_MESSAGE,
            correlation_id=correlation_id,
        )

    def _dispatch_project_story_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse | None:
        """Dispatch POST for project-scoped story mutations (AG3-090)."""
        if _PROJECT_STORIES_COLLECTION.match(route_path):
            return self._handle_post_story(payload, correlation_id)

        for pattern, suffix in (
            (_PROJECT_STORY_APPROVE, "approve"),
            (_PROJECT_STORY_REJECT, "reject"),
            (_PROJECT_STORY_CANCEL, "cancel"),
        ):
            match = pattern.match(route_path)
            if match is not None:
                story_id = match.group("story_id")
                sr = self._story_routes.handle_post(
                    f"/v1/stories/{story_id}/{suffix}",
                    payload,
                    correlation_id,
                )
                if sr is not None:
                    return _story_response_to_http_response(sr)
                return _error_response(
                    HTTPStatus.NOT_FOUND,
                    error_code="not_found",
                    message=_NOT_FOUND_MESSAGE,
                    correlation_id=correlation_id,
                )
        return None

    def _dispatch_new_bc_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse | None:
        """Dispatch POST to the 8 new BC http/ modules (AG3-090)."""
        for routes in (
            self._pipeline_engine_routes,
            self._verify_system_routes,
            self._governance_routes,
            self._closure_routes,
            self._artifacts_routes,
            self._kpi_analytics_routes,
            self._failure_corpus_routes,
            self._requirements_coverage_routes,
            self._task_management_routes,
        ):
            response = routes.handle_post(route_path, payload, correlation_id)
            if response is not None:
                return _bc_response_to_http_response(response)
        return None

    def _handle_put_request(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        # AG3-091 read-only endpoints already returned 405 in _dispatch_method
        # (before body decode); this handler only sees genuine mutation paths.
        planning_response = self._planning_routes.handle_put(
            route_path, payload, correlation_id,
        )
        if planning_response is not None:
            return _planning_response_to_http_response(planning_response)

        # Project-scoped story field PUT (only route; bare /v1/stories/... is not exposed):
        field_match = _PROJECT_STORY_FIELD_KEY.match(route_path)
        if field_match is not None:
            sr = self._story_routes.handle_put(
                f"/v1/stories/{field_match.group('story_id')}"
                f"/fields/{field_match.group('field_key')}",
                payload,
                correlation_id,
            )
            if sr is not None:
                return _story_response_to_http_response(sr)
            return _error_response(
                HTTPStatus.NOT_FOUND,
                error_code="not_found",
                message=_NOT_FOUND_MESSAGE,
                correlation_id=correlation_id,
            )

        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="not_found",
            message=_NOT_FOUND_MESSAGE,
            correlation_id=correlation_id,
        )

    def _handle_delete_request(
        self,
        route_path: str,
        correlation_id: str,
    ) -> HttpResponse:
        # AG3-091 read-only endpoints: DELETE -> 405 (AC1/AC5).
        rm_delete = self._read_model_routes.handle_delete(route_path, correlation_id)
        if rm_delete is not None:
            return _bc_response_to_http_response(rm_delete)

        auth_response = self._auth_routes.handle_delete(
            route_path, {}, correlation_id,
        )
        if auth_response is not None:
            return _auth_response_to_http_response(auth_response)

        planning_response = self._planning_routes.handle_delete(
            route_path, correlation_id,
        )
        if planning_response is not None:
            return _planning_response_to_http_response(planning_response)

        task_delete = self._task_management_routes.handle_delete(route_path, correlation_id)
        if task_delete is not None:
            return _bc_response_to_http_response(task_delete)

        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="not_found",
            message=_NOT_FOUND_MESSAGE,
            correlation_id=correlation_id,
        )

    def _handle_patch_request(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        # AG3-091 read-only endpoints already returned 405 in _dispatch_method
        # (before body decode); this handler only sees genuine mutation paths.
        project_response = self._project_routes.handle_patch(
            route_path, payload, correlation_id,
        )
        if project_response is not None:
            return _project_response_to_http_response(project_response)

        # Project-scoped story PATCH (only route; bare /v1/stories/... is not exposed):
        story_detail_match = _PROJECT_STORY_DETAIL.match(route_path)
        if story_detail_match is not None:
            sr = self._story_routes.handle_patch(
                f"/v1/stories/{story_detail_match.group('story_id')}",
                payload,
                correlation_id,
            )
            if sr is not None:
                return _story_response_to_http_response(sr)
            return _error_response(
                HTTPStatus.NOT_FOUND,
                error_code="not_found",
                message=_NOT_FOUND_MESSAGE,
                correlation_id=correlation_id,
            )

        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="not_found",
            message=_NOT_FOUND_MESSAGE,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Private handler implementations
    # ------------------------------------------------------------------

    def _handle_post_telemetry(
        self,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        try:
            request = TelemetryEventIngestRequest.model_validate(payload)
            accepted = self._telemetry_service.ingest_event(request)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_telemetry_event_payload",
                message="Invalid telemetry event payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except RuntimeError as exc:
            logger.warning("Control-plane telemetry ingest unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="telemetry_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.CREATED,
            accepted.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_post_phase_mutation(
        self,
        *,
        payload: object,
        run_id: str,
        phase: str,
        action: str,
        correlation_id: str,
    ) -> HttpResponse:
        try:
            request = PhaseMutationRequest.model_validate(payload)
            if action == "start":
                result = self._runtime_service.start_phase(
                    run_id=run_id,
                    phase=phase,
                    request=request,
                )
            elif action == "complete":
                result = self._runtime_service.complete_phase(
                    run_id=run_id,
                    phase=phase,
                    request=request,
                )
            else:
                result = self._runtime_service.fail_phase(
                    run_id=run_id,
                    phase=phase,
                    request=request,
                )
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_phase_mutation_payload",
                message="Invalid phase mutation payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except ConfigError as exc:
            return _backend_requirement_response(
                "phase_mutation_unavailable", exc, correlation_id
            )
        except RuntimeError as exc:
            logger.warning("Control-plane phase mutation unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="phase_mutation_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        status = (
            HTTPStatus.CONFLICT
            if result.status == "rejected"
            else HTTPStatus.CREATED
        )
        return _json_response(
            status,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_post_closure_complete(
        self,
        *,
        payload: object,
        run_id: str,
        correlation_id: str,
    ) -> HttpResponse:
        try:
            request = ClosureCompleteRequest.model_validate(payload)
            result = self._runtime_service.complete_closure(
                run_id=run_id,
                request=request,
            )
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_closure_payload",
                message="Invalid closure payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except ConfigError as exc:
            return _backend_requirement_response(
                "closure_unavailable", exc, correlation_id
            )
        except RuntimeError as exc:
            logger.warning("Control-plane closure unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="closure_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.CREATED,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_post_project_edge_sync(
        self,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        try:
            request = ProjectEdgeSyncRequest.model_validate(payload)
            result = self._runtime_service.sync_project_edge(request)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_project_edge_sync_payload",
                message="Invalid project-edge sync payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except ConfigError as exc:
            return _backend_requirement_response(
                "project_edge_sync_unavailable", exc, correlation_id
            )
        except RuntimeError as exc:
            logger.warning("Project-edge sync unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="project_edge_sync_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_get_stories(
        self,
        project_key: str,
        correlation_id: str,
    ) -> HttpResponse:
        try:
            result = self._story_service.list_stories(project_key)
        except RuntimeError as exc:
            logger.warning("Story list unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="story_list_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_post_story(
        self,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        # Delegate to story_routes which already handles POST /v1/stories:
        result = self._story_routes.handle_post(
            "/v1/stories", payload, correlation_id,
        )
        if result is not None:
            return _story_response_to_http_response(result)
        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="not_found",
            message=_NOT_FOUND_MESSAGE,
            correlation_id=correlation_id,
        )

    def _handle_get_story(
        self,
        story_id: str,
        project_key: str,
        correlation_id: str,
    ) -> HttpResponse:
        try:
            result = self._story_service.get_story(project_key, story_id)
        except RuntimeError as exc:
            logger.warning("Story detail unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="story_detail_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        if result is None:
            return _error_response(
                HTTPStatus.NOT_FOUND,
                error_code="story_not_found",
                message="Story not found",
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_get_story_fields(
        self,
        story_id: str,
        correlation_id: str,
    ) -> HttpResponse:
        result = self._story_routes.handle_get(
            f"/v1/stories/{story_id}/fields",
            correlation_id,
            {},
        )
        if result is not None:
            return _story_response_to_http_response(result)
        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="not_found",
            message=_NOT_FOUND_MESSAGE,
            correlation_id=correlation_id,
        )

    def _handle_get_story_search(
        self,
        project_key: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse:
        """GET /v1/projects/{key}/stories/search?q=... (project-scoped, tenant-checked)."""
        result = self._story_routes.handle_get(
            f"/v1/projects/{project_key}/stories/search",
            correlation_id,
            query,
        )
        if result is not None:
            return _story_response_to_http_response(result)
        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="not_found",
            message=_NOT_FOUND_MESSAGE,
            correlation_id=correlation_id,
        )

    def _handle_get_dashboard_board(
        self,
        project_key: str,
        correlation_id: str,
    ) -> HttpResponse:
        try:
            result = self._dashboard_service.get_board(project_key)
        except RuntimeError as exc:
            logger.warning("Dashboard board unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="dashboard_board_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_get_dashboard_story_metrics(
        self,
        project_key: str,
        correlation_id: str,
    ) -> HttpResponse:
        from agentkit.kpi_analytics.errors import AnalyticsNotConfiguredError

        try:
            result = self._dashboard_service.get_story_metrics(project_key, period=None)
        except (RuntimeError, AnalyticsNotConfiguredError) as exc:
            logger.warning("Dashboard metrics unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="dashboard_story_metrics_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )


# ---------------------------------------------------------------------------
# HTTP server entry point
# ---------------------------------------------------------------------------


def serve_control_plane(
    *,
    host: str = "127.0.0.1",
    port: int = 9080,
    certfile: Path,
    keyfile: Path | None = None,
    app: ControlPlaneApplication | None = None,
) -> None:
    """Run the control-plane HTTPS server until interrupted."""

    if app is None:
        from agentkit.auth.middleware import AuthMiddleware

        application = ControlPlaneApplication(auth_middleware=AuthMiddleware())
    else:
        application = app
    server = ThreadingHTTPSServer(
        (host, port),
        _build_handler(application),
        certfile=str(certfile),
        keyfile=str(keyfile) if keyfile is not None else None,
    )
    logger.info(
        "Starting AgentKit control plane on https://%s:%d using %s",
        host,
        port,
        certfile,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _build_handler(app: ControlPlaneApplication) -> type[BaseHTTPRequestHandler]:
    class ControlPlaneHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def do_POST(self) -> None:  # noqa: N802
            self._handle()

        def do_PATCH(self) -> None:  # noqa: N802
            self._handle()

        def do_PUT(self) -> None:  # noqa: N802
            self._handle()

        def do_DELETE(self) -> None:  # noqa: N802
            self._handle()

        def _handle(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length) if content_length > 0 else b""
            response = app.handle_request(
                method=self.command,
                path=self.path,
                body=body,
                request_headers=dict(self.headers.items()),
            )
            self.send_response(response.status_code)
            for key, value in response.headers:
                self.send_header(key, value)
            if not _has_header(response.headers, "Content-Type"):
                self.send_header("Content-Type", "application/json")
            if response.stream is None:
                self.send_header("Content-Length", str(len(response.body)))
                self.end_headers()
                self.wfile.write(response.body)
                return
            self.end_headers()
            for chunk in response.stream:
                self.wfile.write(chunk)
                self.wfile.flush()

        def log_message(self, message_format: str, *args: object) -> None:
            logger.info("control-plane %s", message_format % args)

    return ControlPlaneHandler


# ---------------------------------------------------------------------------
# Helper: project-scoped path detection
# ---------------------------------------------------------------------------


def _is_project_scoped_path(route_path: str) -> bool:
    """Return True for paths that carry a project_key as a path segment.

    Project-scoped paths follow /v1/projects/{key}/<something> (not just
    /v1/projects or /v1/projects/{key} which are the project_management
    special surface).
    """
    match = re.match(r"^/v1/projects/([^/]+)/(.+)$", route_path)
    return match is not None


# ---------------------------------------------------------------------------
# Response converters
# ---------------------------------------------------------------------------


def _json_response(
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    correlation_id: str,
    headers: Sequence[tuple[str, str]] = (),
) -> HttpResponse:
    return HttpResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),) + tuple(headers),
    )


def _project_response_to_http_response(response: ProjectRouteResponse) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
    )


def _auth_response_to_http_response(response: AuthRouteResponse) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
    )


def _auth_middleware_response_to_http_response(
    response: AuthMiddlewareResponse,
) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
    )


def _concept_response_to_http_response(response: ConceptRouteResponse) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
    )


def _hub_response_to_http_response(response: MultiLlmHubRouteResponse) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
        stream=response.stream,
    )


def _planning_response_to_http_response(
    response: ExecutionPlanningRouteResponse,
) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
    )


def _story_response_to_http_response(response: StoryRouteResponse) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
    )


def _telemetry_response_to_http_response(
    response: TelemetryRouteResponse,
) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
        stream=response.stream,
    )


def _bc_response_to_http_response(response: object) -> HttpResponse:
    """Convert any BC route response (dataclass with status_code/body/headers)."""
    return HttpResponse(
        status_code=getattr(response, "status_code", 500),
        body=getattr(response, "body", b""),
        headers=getattr(response, "headers", ()),
    )


def _error_response(
    status: HTTPStatus,
    *,
    error_code: str,
    message: str,
    correlation_id: str,
    detail: object | None = None,
    headers: Sequence[tuple[str, str]] = (),
) -> HttpResponse:
    payload = ApiErrorResponse(
        error_code=error_code,
        error=message,
        correlation_id=correlation_id,
        detail=detail,
    ).model_dump(mode="json", exclude_none=True)
    return _json_response(
        status,
        payload,
        correlation_id=correlation_id,
        headers=headers,
    )


def _backend_requirement_response(
    error_code: str,
    exc: ConfigError,
    correlation_id: str,
) -> HttpResponse:
    """Map a backend-requirement ``ConfigError`` to a structured 503."""
    logger.warning("Control-plane backend requirement unmet: %s", exc)
    return _error_response(
        HTTPStatus.SERVICE_UNAVAILABLE,
        error_code=error_code,
        message=str(exc),
        correlation_id=correlation_id,
    )


def _decode_json_body(body: bytes, correlation_id: str) -> object | HttpResponse:
    try:
        return cast("object", json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error_response(
            HTTPStatus.BAD_REQUEST,
            error_code="invalid_json",
            message="Request body must be valid JSON",
            correlation_id=correlation_id,
        )


def _resolve_correlation_id(request_headers: Mapping[str, str] | None) -> str:
    # HTTP header names are case-insensitive (RFC 9110 §5.1). The official client
    # sends ``X-Correlation-Id`` but ``urllib`` (and intermediaries) may normalize
    # the casing on the wire, so an EXACT-case lookup would miss the client's id
    # and the control plane would mint a divergent ``req-<uuid>`` (FK-91 §91.1a
    # Regel #7 violation). Resolve the header case-insensitively so the client's
    # correlation id is adopted regardless of the transmitted casing.
    if request_headers is not None:
        provided = _lookup_header_ci(request_headers, _CORRELATION_HEADER)
        if provided is not None:
            value = provided.strip()
            if value:
                return value
    return f"req-{uuid.uuid4().hex}"


def _lookup_header_ci(headers: Mapping[str, str], name: str) -> str | None:
    """Look a request header up case-insensitively (HTTP headers are case-insensitive)."""
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def _has_header(headers: Sequence[tuple[str, str]], name: str) -> bool:
    normalized = name.lower()
    return any(key.lower() == normalized for key, _value in headers)
