"""HTTPS transport and routing for the AgentKit control plane (FK-72 §72.8.2).

This is the canonical implementation (moved from ``control_plane/http.py``
by AG3-090).  ``agentkit.backend.control_plane.http`` holds a compat re-export only.
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

from agentkit.backend.auth.middleware import AuthMiddlewareResponse
from agentkit.backend.control_plane.guard_counter import ControlPlaneGuardCounterService
from agentkit.backend.control_plane.models import (
    AdminAbortRequest,
    ApiErrorResponse,
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    GuardCounterMutationRequest,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
    TelemetryEventIngestRequest,
    op_id_validation_error,
)
from agentkit.backend.control_plane.ownership_fence import ERROR_CODE_OWNERSHIP_TRANSFERRED
from agentkit.backend.control_plane.runtime import (
    ControlPlaneRuntimeService,
    OperationNotAbortableError,
    OperationNotFoundError,
)
from agentkit.backend.control_plane.telemetry import ControlPlaneTelemetryService
from agentkit.backend.control_plane.worker_health import ControlPlaneWorkerHealthService
from agentkit.backend.control_plane_http._route_patterns import (
    _OPERATION_ADMIN_ABORT_PATTERN,
    _OPERATION_PATH_PATTERN,
    _PROJECT_CLOSURE_PATH_PATTERN,
    _PROJECT_DASHBOARD_BOARD,
    _PROJECT_DASHBOARD_STORY_METRICS,
    _PROJECT_PHASE_PATH_PATTERN,
    _PROJECT_STORIES_COLLECTION,
    _PROJECT_STORY_APPROVE,
    _PROJECT_STORY_CANCEL,
    _PROJECT_STORY_DETAIL,
    _PROJECT_STORY_FIELD_KEY,
    _PROJECT_STORY_FIELDS,
    _PROJECT_STORY_REJECT,
    _PROJECT_STORY_SEARCH,
)
from agentkit.backend.control_plane_http.tenant_scope import TenantScopeMiddleware
from agentkit.backend.control_plane_http.version_handshake import CompatWindow, VersionHandshakeMiddleware
from agentkit.backend.exceptions import ConfigError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from pathlib import Path

    from agentkit.backend.auth.http.routes import AuthRouteResponse, AuthRoutes
    from agentkit.backend.auth.middleware import AuthMiddleware
    from agentkit.backend.concept_catalog.http.routes import ConceptCatalogRoutes, ConceptRouteResponse
    from agentkit.backend.execution_planning.http.routes import ExecutionPlanningRouteResponse, ExecutionPlanningRoutes
    from agentkit.backend.kpi_analytics.dashboard import DashboardService
    from agentkit.backend.kpi_analytics.http.routes import KpiAnalyticsRoutes
    from agentkit.backend.project_management.http.routes import ProjectManagementRoutes, ProjectRouteResponse
    from agentkit.backend.project_management.read_model_routes import ReadModelRoutes
    from agentkit.backend.story.service import StoryService
    from agentkit.backend.story_context_manager.http.routes import StoryContextRoutes, StoryRouteResponse
    from agentkit.backend.task_management.http.routes import TaskManagementRoutes
    from agentkit.backend.telemetry.http.routes import TelemetryRouteResponse, TelemetryRoutes
    from agentkit.integration_clients.multi_llm_hub.http.routes import MultiLlmHubRouteResponse, MultiLlmHubRoutes

logger = logging.getLogger(__name__)

# Route path patterns (FK-72 §72.8.1) are defined in the sibling ``_route_patterns``
# module (imported at the top of this file) so this module's executed top-level stays
# lean (PY_MODULE_TOP_LEVEL_MAX_LOC_100); they are used under their original names, so
# route matching is unchanged.

_NOT_FOUND_MESSAGE = "Not found"
_CORRELATION_HEADER = "X-Correlation-Id"


# ---------------------------------------------------------------------------
# Default-builder helpers (lazy imports)
# ---------------------------------------------------------------------------


def _build_default_story_service() -> StoryService:
    """Build the BFF story read service through the Story-BC ``StoryReadPort``.

    FK-07 §7.6: the default wiring routes story list/detail reads through the
    published port adapter (composition root), never a state-backend passthrough.
    """
    from agentkit.backend.bootstrap.composition_root import build_story_read_service

    return build_story_read_service()


def _build_default_project_routes() -> ProjectManagementRoutes:
    from agentkit.backend.bootstrap.composition_root import build_project_repository
    from agentkit.backend.project_management.http.routes import ProjectManagementRoutes
    from agentkit.backend.story_context_manager.service import (
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

    # FK-07 §7.6/§7.9 (AG3-127): the BFF composition root owns the project read
    # adapter wiring — inject the ``ProjectRepository`` port through the
    # composition root instead of relying on the BC-internal default.
    return ProjectManagementRoutes(
        repos_in_use_checker=_repos_in_use_checker,
        repository=build_project_repository(),
    )


def _build_default_story_routes() -> StoryContextRoutes:
    from agentkit.backend.story_context_manager.http.routes import StoryContextRoutes

    return StoryContextRoutes()


def _build_default_concept_routes() -> ConceptCatalogRoutes:
    from agentkit.backend.concept_catalog.http.routes import ConceptCatalogRoutes

    return ConceptCatalogRoutes()


def _build_default_hub_routes() -> MultiLlmHubRoutes:
    from agentkit.integration_clients.multi_llm_hub.http.routes import MultiLlmHubRoutes

    return MultiLlmHubRoutes()


def _build_default_planning_routes() -> ExecutionPlanningRoutes:
    from agentkit.backend.execution_planning.http.routes import ExecutionPlanningRoutes

    return ExecutionPlanningRoutes()


def _build_default_telemetry_routes() -> TelemetryRoutes:
    from agentkit.backend.bootstrap.composition_root import (
        build_project_telemetry_event_source,
    )
    from agentkit.backend.telemetry.http.routes import TelemetryRoutes

    # FK-07 §7.6/§7.8 (AG3-127): the BFF composition root owns the telemetry read
    # adapter wiring — inject the ``ProjectTelemetryEventSource`` port; the
    # telemetry BC no longer self-instantiates a state-backend adapter.
    return TelemetryRoutes(build_project_telemetry_event_source())


def _build_default_auth_routes(auth_middleware: AuthMiddleware | None) -> AuthRoutes:
    from agentkit.backend.auth.http.routes import AuthRoutes

    if auth_middleware is not None:
        return AuthRoutes(
            session_store=auth_middleware.session_store,
            token_repository=auth_middleware.token_repository,
        )
    return AuthRoutes()


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
    from agentkit.backend.bootstrap.composition_root import build_kpi_analytics_read_facade
    from agentkit.backend.kpi_analytics.http.routes import KpiAnalyticsRoutes

    return KpiAnalyticsRoutes(kpi_analytics=build_kpi_analytics_read_facade())


def _build_default_task_management_routes() -> TaskManagementRoutes:
    """Build the default task-management BC route handler backed by real storage."""
    from agentkit.backend.bootstrap.composition_root import build_task_management_routes

    return build_task_management_routes()


def _build_default_read_model_routes() -> ReadModelRoutes:
    from agentkit.backend.bootstrap.composition_root import build_project_read_model_routes

    return build_project_read_model_routes()


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

    Collects all BC-route and middleware route overrides into a single
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
    kpi_analytics_routes: KpiAnalyticsRoutes | None = None
    read_model_routes: ReadModelRoutes | None = None
    task_management_routes: TaskManagementRoutes | None = None


# ---------------------------------------------------------------------------
# ControlPlaneApplication
# ---------------------------------------------------------------------------


class _GovernanceMediationHandlers:
    """Governance hook-mediation HTTP handlers (AG3-129), split out of the app.

    Extracted from :class:`ControlPlaneApplication` so that transport class stays
    within the per-class LOC budget (``PY_CLASS_MAX_LOC_800``) WITHOUT any
    behaviour change: these handlers depend only on the injected mediation
    services and the module-level response helpers, never on the app's routing
    state. The three collaborators are supplied by
    ``ControlPlaneApplication.__init__``; they are declared here as annotations
    for the type checker (the mixin never constructs them).
    """

    _telemetry_service: ControlPlaneTelemetryService
    _guard_counter_service: ControlPlaneGuardCounterService
    _worker_health_service: ControlPlaneWorkerHealthService

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

    def _handle_post_guard_counter(
        self,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        """Apply a guard-invocation counter mutation (AG3-129, FK-61 §61.4.3)."""
        from agentkit.backend.story_context_manager.errors import (
            IdempotencyMismatchError,
        )

        try:
            request = GuardCounterMutationRequest.model_validate(payload)
            accepted = self._guard_counter_service.apply(request)
        except ValidationError as exc:
            # AG3-140 (FK-91 §91.1a Rule 5, AC1): a missing/empty op_id fails
            # closed with 422, distinct from an ordinary 400 payload-shape defect.
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY
                if op_id_validation_error(exc)
                else HTTPStatus.BAD_REQUEST,
                error_code="invalid_guard_counter_payload",
                message="Invalid guard-counter mutation payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except IdempotencyMismatchError as exc:
            # FK-91 §91.1a Rule 5: same op_id + different body -> fail-closed 409.
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="idempotency_mismatch",
                message=str(exc),
                correlation_id=correlation_id,
                detail=exc.detail,
            )
        except RuntimeError as exc:
            logger.warning("Guard-counter mutation unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="guard_counter_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.CREATED,
            accepted.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_get_worker_health(
        self,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse:
        """Read canonical worker-health state (AG3-129, FK-30 §30.10)."""
        story_id = _single_query_value(query, "story_id")
        worker_id = _single_query_value(query, "worker_id")
        if not story_id or not worker_id:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_worker_health_query",
                message="story_id and worker_id query parameters are required",
                correlation_id=correlation_id,
            )
        try:
            result = self._worker_health_service.load(
                story_id=story_id, worker_id=worker_id
            )
        except RuntimeError as exc:
            logger.warning("Worker-health read unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="worker_health_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_post_worker_health(
        self,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        """Write canonical worker-health state (AG3-129, FK-30 §30.10)."""
        try:
            accepted = self._worker_health_service.save(payload)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_worker_health_payload",
                message="Invalid worker-health state payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except RuntimeError as exc:
            logger.warning("Worker-health write unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="worker_health_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.CREATED,
            accepted.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_get_telemetry_events(
        self,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse:
        """Read canonical execution events for one scope (AG3-129)."""
        project_key = _single_query_value(query, "project_key")
        story_id = _single_query_value(query, "story_id")
        event_type = _single_query_value(query, "event_type")
        if not project_key or not story_id:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_telemetry_query",
                message="project_key and story_id query parameters are required",
                correlation_id=correlation_id,
            )
        try:
            result = self._telemetry_service.query_events(
                project_key=project_key,
                story_id=story_id,
                event_type=event_type,
            )
        except RuntimeError as exc:
            logger.warning("Telemetry read unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="telemetry_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )


class _StoryDashboardHandlersMixin:
    """Story + dashboard resource HTTP handlers (extracted mixin).

    Cohesive story collection/detail/fields/search and dashboard board/story-metrics
    handlers, split out of :class:`ControlPlaneApplication` for cohesion (no
    behaviour change). The concrete application supplies the dependencies below.
    """

    if TYPE_CHECKING:
        _story_service: StoryService
        _story_routes: StoryContextRoutes
        _dashboard_service: DashboardService

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
        from agentkit.backend.kpi_analytics.errors import AnalyticsNotConfiguredError

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


class ControlPlaneApplication(
    _StoryDashboardHandlersMixin, _GovernanceMediationHandlers
):
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
        guard_counter_service: ControlPlaneGuardCounterService | None = None,
        worker_health_service: ControlPlaneWorkerHealthService | None = None,
        runtime_service: ControlPlaneRuntimeService | None = None,
        story_service: StoryService | None = None,
        dashboard_service: DashboardService | None = None,
        auth_middleware: AuthMiddleware | None = None,
        tenant_scope_middleware: TenantScopeMiddleware | None = None,
        version_handshake_middleware: VersionHandshakeMiddleware | None = None,
    ) -> None:
        r = routes or ControlPlaneApplicationRoutes()
        self._telemetry_service = telemetry_service or ControlPlaneTelemetryService()
        self._guard_counter_service = (
            guard_counter_service or ControlPlaneGuardCounterService()
        )
        self._worker_health_service = (
            worker_health_service or ControlPlaneWorkerHealthService()
        )
        self._runtime_service = runtime_service or ControlPlaneRuntimeService()
        self._story_service = story_service or _build_default_story_service()
        self._dashboard_service = self._resolve_dashboard_service(dashboard_service)
        self._auth_middleware = auth_middleware
        self._init_default_routes(r, auth_middleware)
        self._tenant_scope = tenant_scope_middleware or TenantScopeMiddleware()
        # Opt-in like ``auth_middleware``; production wires it ON in
        # ``serve_control_plane`` (FK-91 §91.1a Rule 11). The announced
        # ``/v1/compat`` window is the middleware's, else the central default.
        self._version_handshake = version_handshake_middleware
        self._compat_window: CompatWindow = (
            version_handshake_middleware or VersionHandshakeMiddleware()
        ).window
        self._init_bc_routes(r)

    def _resolve_dashboard_service(
        self, dashboard_service: DashboardService | None
    ) -> DashboardService:
        """Return the injected dashboard service, else build the default (S3776 split)."""
        if dashboard_service is not None:
            return dashboard_service
        from agentkit.backend.bootstrap.composition_root import build_dashboard_service

        return build_dashboard_service(self._story_service)

    def _init_default_routes(
        self,
        r: ControlPlaneApplicationRoutes,
        auth_middleware: AuthMiddleware | None,
    ) -> None:
        """Populate the per-BC route tables, defaulting any the caller omitted.

        Extracted from ``__init__`` so the constructor's cognitive complexity
        stays within the S3776 budget (the seven ``or``-default assignments live
        here instead of inline). No behaviour change.
        """
        self._project_routes = r.project_routes or _build_default_project_routes()
        self._story_routes = r.story_routes or _build_default_story_routes()
        self._concept_routes = r.concept_routes or _build_default_concept_routes()
        self._hub_routes = r.hub_routes or _build_default_hub_routes()
        self._planning_routes = r.planning_routes or _build_default_planning_routes()
        self._telemetry_routes = (
            r.telemetry_routes or _build_default_telemetry_routes()
        )
        self._auth_routes = r.auth_routes or _build_default_auth_routes(auth_middleware)

    def _init_bc_routes(self, r: ControlPlaneApplicationRoutes) -> None:
        """Initialise the grounded BC route handlers (extracted to reduce S3776 complexity)."""
        self._kpi_analytics_routes = (
            r.kpi_analytics_routes or _build_default_kpi_analytics_routes()
        )
        self._read_model_routes = (
            r.read_model_routes or _build_default_read_model_routes()
        )
        self._task_management_routes = (
            r.task_management_routes or _build_default_task_management_routes()
        )

    def ensure_version_handshake(self) -> None:
        """Guarantee a fail-closed handshake middleware on the production listener.

        The constructor keeps the handshake opt-in (direct-construction tests stay
        ungated), but the real listener must never serve an ungated app (FK-91
        §91.1a Rule 11 / FK-10 §10.2.8: no fail-open default). This injects the
        central default when none was wired, closing the fail-open path.
        """
        if self._version_handshake is None:
            self._version_handshake = VersionHandshakeMiddleware()
            self._compat_window = self._version_handshake.window

    def run_pre_serve_startup_hook(self) -> None:
        """Resolve THIS boot's instance identity + reconcile orphans (AG3-138 IMPL-003).

        The single pre-serve startup hook, invoked by :func:`serve_control_plane`
        BETWEEN app construction and ``serve_forever()`` -- so the listener
        accepts its FIRST request only after it has run successfully (AC1). It:

        1. resolves THIS boot's backend instance identity (stable id, monotone
           incarnation; :mod:`instance_identity`);
        2. finalizes every orphaned ``claimed`` operation of THIS instance's
           OWN earlier incarnations (never a foreign identity), routing
           partial writes into the explicit ``repair`` state
           (:mod:`startup_reconcile`);
        3. binds the resolved identity into the runtime service so every
           subsequently-accepted claim carries it.

        Fail-closed (AC9): any failure propagates uncaught -- the process never
        reaches ``serve_forever()`` with an unclear claim inventory.
        """
        from agentkit.backend.control_plane.instance_identity import (
            resolve_backend_instance_identity,
        )
        from agentkit.backend.control_plane.repository import (
            BackendInstanceIdentityRepository,
        )
        from agentkit.backend.control_plane.startup_reconcile import (
            run_startup_reconciliation,
        )

        identity = resolve_backend_instance_identity(BackendInstanceIdentityRepository())
        run_startup_reconciliation(
            self._runtime_service.repository,
            identity,
            object_claim_repo=self._runtime_service.object_claim_repository,
        )
        self._runtime_service.bind_instance_identity(identity)
        logger.info(
            "Startup reconciliation complete for backend instance %s "
            "(incarnation %d); listener may accept requests.",
            identity.backend_instance_id,
            identity.instance_incarnation,
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

        def _dispatch() -> HttpResponse:
            return self._dispatch_method(method, route_path, query, body, correlation_id, request_headers)

        # Version handshake (FK-91 §91.1a Rule 11): after auth/tenant, before
        # routing. The middleware fails closed (426) for incompatible /
        # handshake-less mutations and otherwise carries the announce/WARNING
        # headers onto the dispatched response (owner: VersionHandshakeMiddleware).
        if self._version_handshake is not None:
            return self._version_handshake.guard(
                method=method,
                route_path=route_path,
                request_headers=request_headers,
                correlation_id=correlation_id,
                dispatch=_dispatch,
            )
        return _dispatch()

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
            return self._handle_delete_request(route_path, body, correlation_id)
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
        # Version compat window (non-project-scoped, read-only, handshake-exempt
        # to avoid the hen-and-egg trap; FK-91 §91.1a / FK-10 §10.2.7):
        if route_path == "/v1/compat":
            return _json_response(
                HTTPStatus.OK,
                self._compat_window.model_dump(mode="json"),
                correlation_id=correlation_id,
            )

        # AG3-129 hook-mediation reads (non-project-scoped, mirror /v1/telemetry/events):
        if route_path == "/v1/telemetry/events":
            return self._handle_get_telemetry_events(query, correlation_id)
        if route_path == "/v1/governance/worker-health":
            return self._handle_get_worker_health(query, correlation_id)

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

        # Grounded BC GET routes (kpi_analytics, task_management; project-scoped):
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
            self._kpi_analytics_routes,
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
        # AG3-129 hook-mediation writes (non-project-scoped, mirror telemetry ingest):
        if route_path == "/v1/governance/guard-counters":
            return self._handle_post_guard_counter(payload, correlation_id)
        if route_path == "/v1/governance/worker-health":
            return self._handle_post_worker_health(payload, correlation_id)
        if route_path == "/v1/project-edge/sync":
            return self._handle_post_project_edge_sync(payload, correlation_id)

        # AG3-138 admin-abort (non-project-scoped, mirrors the operation GET path):
        admin_abort_match = _OPERATION_ADMIN_ABORT_PATTERN.match(route_path)
        if admin_abort_match is not None:
            return self._handle_post_admin_abort(
                op_id=admin_abort_match.group("op_id"),
                payload=payload,
                correlation_id=correlation_id,
            )

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

        # Grounded BC POST routes (kpi_analytics, task_management):
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
        """Dispatch POST to the grounded BC http/ modules (AG3-090)."""
        for routes in (
            self._kpi_analytics_routes,
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
        body: bytes,
        correlation_id: str,
    ) -> HttpResponse:
        # AG3-091 read-only endpoints: DELETE -> 405 (AC1/AC5).
        rm_delete = self._read_model_routes.handle_delete(route_path, correlation_id)
        if rm_delete is not None:
            return _bc_response_to_http_response(rm_delete)

        # AG3-140 (FK-91 §91.1a Rule 5): the token-revoke DELETE carries the
        # client-supplied op_id in its (optional) JSON body -- an empty body
        # decodes to {} so a route that needs no payload is unaffected, but the
        # auth revoke route can now see a real op_id instead of a hardcoded {}.
        payload = _decode_optional_json_body(body, correlation_id)
        if isinstance(payload, HttpResponse):
            return payload
        auth_response = self._auth_routes.handle_delete(
            route_path, payload, correlation_id,
        )
        if auth_response is not None:
            return _auth_response_to_http_response(auth_response)

        # AG3-140: the dependency DELETE is a mutating route under the full
        # idempotency contract, so it too receives the decoded DELETE body (which
        # carries the required client op_id), exactly like the auth revoke route.
        planning_response = self._planning_routes.handle_delete(
            route_path, payload, correlation_id,
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

    def _handle_post_phase_mutation(
        self,
        *,
        payload: object,
        run_id: str,
        phase: str,
        action: str,
        correlation_id: str,
    ) -> HttpResponse:
        from agentkit.backend.story_context_manager.errors import (
            IdempotencyMismatchError,
        )

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
            elif action == "fail":
                result = self._runtime_service.fail_phase(
                    run_id=run_id,
                    phase=phase,
                    request=request,
                )
            else:
                # AG3-130: resume a PAUSED phase; the core drives the pipeline
                # engine's resume path server-side (FK-45, FK-91 §91.1a).
                result = self._runtime_service.resume_phase(
                    run_id=run_id,
                    phase=phase,
                    request=request,
                )
        except ValidationError as exc:
            # AG3-140 (FK-91 §91.1a Rule 5, AC1): a missing/empty op_id fails
            # closed with 422, distinct from an ordinary 400 payload-shape defect.
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY
                if op_id_validation_error(exc)
                else HTTPStatus.BAD_REQUEST,
                error_code="invalid_phase_mutation_payload",
                message="Invalid phase mutation payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except IdempotencyMismatchError as exc:
            # AG3-140 finding 3 (FK-91 §91.1a Rule 5): a terminal op_id replayed
            # with a DIFFERENT phase/action/body is fail-closed 409, not a wrong
            # replay of the stored result.
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="idempotency_mismatch",
                message=str(exc),
                correlation_id=correlation_id,
                detail=exc.detail,
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
        return _mutation_result_response(result, correlation_id=correlation_id)

    def _handle_post_closure_complete(
        self,
        *,
        payload: object,
        run_id: str,
        correlation_id: str,
    ) -> HttpResponse:
        from agentkit.backend.story_context_manager.errors import (
            IdempotencyMismatchError,
        )

        try:
            request = ClosureCompleteRequest.model_validate(payload)
            result = self._runtime_service.complete_closure(
                run_id=run_id,
                request=request,
            )
        except ValidationError as exc:
            # AG3-140 (FK-91 §91.1a Rule 5, AC1): a missing/empty op_id fails
            # closed with 422, distinct from an ordinary 400 payload-shape defect.
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY
                if op_id_validation_error(exc)
                else HTTPStatus.BAD_REQUEST,
                error_code="invalid_closure_payload",
                message="Invalid closure payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except IdempotencyMismatchError as exc:
            # AG3-140 finding 3: a terminal op_id replayed with a different
            # closure body is fail-closed 409 idempotency_mismatch.
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="idempotency_mismatch",
                message=str(exc),
                correlation_id=correlation_id,
                detail=exc.detail,
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
        #: AG3-138 AC10: a repair-locked (or otherwise ``rejected``) closure maps to
        #: 409 -- identical wiring to the phase mutation entrypoint. Previously this
        #: path returned 201 CREATED unconditionally, letting a rejected closure look
        #: like a success (fail-closed violation).
        return _mutation_result_response(result, correlation_id=correlation_id)

    def _handle_post_project_edge_sync(
        self,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        try:
            request = ProjectEdgeSyncRequest.model_validate(payload)
            result = self._runtime_service.sync_project_edge(request)
        except ValidationError as exc:
            # AG3-140 (FK-91 §91.1a Rule 5, AC1): a missing/empty op_id fails
            # closed with 422, distinct from an ordinary 400 payload-shape defect.
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY
                if op_id_validation_error(exc)
                else HTTPStatus.BAD_REQUEST,
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

    def _handle_post_admin_abort(
        self,
        *,
        op_id: str,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        """POST /v1/project-edge/operations/{op_id}/admin-abort (AG3-138).

        FK-91 §91.1a ``admin_abort_inflight_operation`` (op-class
        ``admin_transition``, FK-55 §55.5). Deterministic, fail-closed error
        contract (AC6): an unknown ``op_id`` -> 404 ``operation_not_found``; a
        target that is not a live in-flight claim (already terminal / resolved
        concurrently) -> 409 ``operation_not_abortable``. On success the terminal
        ``aborted`` / ``repair`` result (200) carries the audited ``admin_note``;
        a partial write target goes to ``repair`` (IMPL-005) and mutation-locks its
        story (AC10). Minimal authorization: the mandatory audited actor
        (``session_id`` / ``principal_type``) and ``reason`` are recorded on the
        terminal record; the full HTTP principal-attestation infrastructure
        (IMPL-018) is explicitly a follow-up story (AG3-148/AG3-154).
        """
        try:
            request = AdminAbortRequest.model_validate(payload)
            result = self._runtime_service.admin_abort_inflight_operation(op_id, request)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_admin_abort_payload",
                message="Invalid admin-abort payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except OperationNotFoundError:
            return _error_response(
                HTTPStatus.NOT_FOUND,
                error_code="operation_not_found",
                message=f"Operation {op_id!r} not found",
                correlation_id=correlation_id,
            )
        except OperationNotAbortableError as exc:
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="operation_not_abortable",
                message=str(exc),
                correlation_id=correlation_id,
                detail={"current_status": exc.current_status},
            )
        except ConfigError as exc:
            return _backend_requirement_response(
                "admin_abort_unavailable", exc, correlation_id
            )
        except RuntimeError as exc:
            logger.warning("Admin-abort unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="admin_abort_unavailable",
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
    startup_hook: Callable[[ControlPlaneApplication], None] | None = None,
) -> None:
    """Run the control-plane HTTPS server until interrupted.

    AG3-138 IMPL-003: ``startup_hook`` is the pre-serve hook run BETWEEN app
    construction and ``serve_forever()``; it defaults to the productive
    :meth:`ControlPlaneApplication.run_pre_serve_startup_hook` (instance-identity
    resolution + orphan reconciliation, fail-closed). It is an injection seam so
    a transport-wiring unit test can drive server start/close without a live
    control-plane backend; the productive listener always runs the real hook.
    """

    if app is None:
        from agentkit.backend.auth.middleware import AuthMiddleware

        # Production wires the handshake middleware ON (fail-closed by default,
        # FK-91 §91.1a Rule 11 / FK-10 §10.2.8): no fail-open default on the
        # real listener, mirroring the always-on auth middleware here.
        application = ControlPlaneApplication(
            auth_middleware=AuthMiddleware(),
            version_handshake_middleware=VersionHandshakeMiddleware(),
        )
    else:
        application = app
    # GUARANTEE the real listener is handshake-gated even when an app was injected
    # without a handshake middleware (close the fail-OPEN path; FK-91 Rule 11).
    application.ensure_version_handshake()
    # AG3-138 IMPL-003: the pre-serve startup hook runs BEFORE the socket is bound
    # and BEFORE ``serve_forever()`` -- so the listener accepts its first request
    # only after instance-identity resolution + orphan reconciliation succeed. A
    # failure here (fail-closed, AC9) propagates uncaught: the server never starts
    # with an unclear claim inventory.
    hook = startup_hook or (lambda a: a.run_pre_serve_startup_hook())
    hook(application)
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


def _mutation_result_response(
    result: ControlPlaneMutationResult,
    *,
    correlation_id: str,
) -> HttpResponse:
    """Map a control-plane mutation result to its fail-closed HTTP status (AG3-138).

    A ``rejected`` result -- the fail-closed outcome of EVERY mutating control-plane
    entrypoint (``start``/``complete``/``fail``/``resume``/``closure``), including the
    AC10 open-reconcile/repair mutation lock -- maps to 409 CONFLICT; any other
    (committed / replayed) result maps to 201 CREATED. Centralizing this here keeps
    the rejected->409 wiring identical across phase mutations and closure completion,
    so no mutating entrypoint can return 2xx for a fail-closed rejection.

    AG3-142 (FK-91 §91.1a Rule 18): the ONE exception is the ex-owner
    ``ownership_transferred`` rejection, which maps to 403 FORBIDDEN instead of
    the generic 409 -- the caller is not merely conflicting with concurrent
    state, it no longer holds run-ownership at all. The structured
    ``ownership_conflict`` detail (reason, new owner, transfer instant) travels
    on the SAME ``ControlPlaneMutationResult`` body, embedded per the FK-91
    Rule 8 error contract (``error_code`` here; ``correlation_id`` via the
    ``X-Correlation-Id`` header on every response, Rule 7).

    AG3-141 (K4, IMPL-016): a busy-object-claim rejection additionally carries
    ``retry_after_seconds`` -- surfaced here as a ``Retry-After`` header (the
    deterministic wait contract; never a blocking wait). Every other rejection
    cause carries no such header (unchanged behaviour).
    """
    if result.status != "rejected":
        status = HTTPStatus.CREATED
    elif result.error_code == ERROR_CODE_OWNERSHIP_TRANSFERRED:
        status = HTTPStatus.FORBIDDEN
    else:
        status = HTTPStatus.CONFLICT
    headers: tuple[tuple[str, str], ...] = ()
    if result.retry_after_seconds is not None:
        headers = (("Retry-After", str(result.retry_after_seconds)),)
    return _json_response(
        status,
        result.model_dump(mode="json"),
        correlation_id=correlation_id,
        headers=headers,
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


def _decode_optional_json_body(
    body: bytes, correlation_id: str
) -> object | HttpResponse:
    """Decode a request body that may legitimately be empty (DELETE routes).

    An empty body decodes to ``{}`` so a route needing no payload is unaffected;
    a non-empty body must still be valid JSON (fail-closed ``invalid_json`` on a
    malformed one). AG3-140: the token-revoke DELETE carries its client-supplied
    ``op_id`` (FK-91 §91.1a Rule 5) in this optional body.
    """
    if not body or not body.strip():
        return {}
    return _decode_json_body(body, correlation_id)


def _single_query_value(query: dict[str, list[str]], key: str) -> str | None:
    """Return the first value for ``key`` in a parsed query string, or ``None``."""
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _resolve_correlation_id(request_headers: Mapping[str, str] | None) -> str:
    # HTTP header names are case-insensitive (RFC 9110 §5.1). The official client
    # sends ``X-Correlation-Id`` but ``urllib`` (and intermediaries) may normalize
    # the casing on the wire, so an EXACT-case lookup would miss the client's id
    # and the control plane would mint a divergent ``req-<uuid>`` (FK-91 §91.1a
    # Rule #7 violation). Resolve the header case-insensitively so the client's
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
