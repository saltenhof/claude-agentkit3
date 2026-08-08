"""Routing surface of the AgentKit control plane (FK-72 §72.8.2).

This module owns the App / Router-Registry: it turns ONE admitted request into
ONE :class:`HttpResponse` by dispatching it to the owning bounded context. It
deliberately owns neither of the two questions that used to live alongside it:

* *who may reach a route at all* -- ``surface_policy.py``,
* *how bytes reach the socket and when a listener starts or stops* --
  ``wire_adapter.py`` and ``server.py``.

This is the canonical AND only implementation (moved from ``control_plane/http.py``
by AG3-090); the re-export facade that survived that move was deleted by AG3-229.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from http import HTTPStatus
from threading import Event, RLock
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from agentkit.backend.control_plane.guard_counter import ControlPlaneGuardCounterService
from agentkit.backend.control_plane.telemetry import ControlPlaneTelemetryService
from agentkit.backend.control_plane.worker_health import ControlPlaneWorkerHealthService
from agentkit.backend.control_plane.writer_lease import ControlPlaneWriterLeaseLostError
from agentkit.backend.control_plane_http import _route_patterns
from agentkit.backend.control_plane_http.tenant_scope import TenantScopeMiddleware
from agentkit.backend.control_plane_http.version_handshake import CompatWindow, VersionHandshakeMiddleware

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from agentkit.backend.auth.middleware import AuthMiddleware, AuthResult
    from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
    from agentkit.backend.control_plane.writer_lease import (
        ControlPlaneWriterLease,
    )
    from agentkit.backend.kpi_analytics.dashboard import DashboardService
    from agentkit.backend.story.service import StoryService
    from agentkit.backend.story_context_manager.http.routes import StoryContextRoutes

from agentkit.backend.control_plane_http.bc_dispatch import _GroundedBcDispatchMixin
from agentkit.backend.control_plane_http.default_routes import (
    _build_default_auth_routes,
    _build_default_concept_routes,
    _build_default_failure_corpus_routes,
    _build_default_hub_routes,
    _build_default_installer_writer_routes,
    _build_default_kpi_analytics_routes,
    _build_default_planning_routes,
    _build_default_project_routes,
    _build_default_read_model_routes,
    _build_default_runtime_service,
    _build_default_story_admin_routes,
    _build_default_story_routes,
    _build_default_story_service,
    _build_default_story_split_routes,
    _build_default_takeover_approval_routes,
    _build_default_task_management_routes,
    _build_default_telemetry_routes,
    _build_default_third_party_validation_routes,
)
from agentkit.backend.control_plane_http.edge_read_handlers import (
    _handle_get_open_commands,
    _handle_get_operation,
    _handle_get_push_freshness,
    _handle_get_push_ownership,
    _handle_healthz,
    _read_only_method_not_allowed,
)
from agentkit.backend.control_plane_http.governance_mediation import _GovernanceMediationHandlers
from agentkit.backend.control_plane_http.installer_routes import InstallerDispatchMixin
from agentkit.backend.control_plane_http.responses import (
    HttpResponse as HttpResponse,
)
from agentkit.backend.control_plane_http.responses import (
    _auth_response_to_http_response,
    _bc_response_to_http_response,
    _concept_response_to_http_response,
    _decode_json_body,
    _decode_optional_json_body,
    _error_response,
    _hub_response_to_http_response,
    _json_response,
    _planning_response_to_http_response,
    _project_response_to_http_response,
    _resolve_correlation_id,
    _story_response_to_http_response,
    _telemetry_response_to_http_response,
)
from agentkit.backend.control_plane_http.routes_config import (
    ControlPlaneApplicationRoutes as ControlPlaneApplicationRoutes,
)
from agentkit.backend.control_plane_http.runtime_mutation_handlers import (
    _RuntimeMutationHandlers,
)
from agentkit.backend.control_plane_http.startup import run_pre_serve_startup
from agentkit.backend.control_plane_http.surface_policy import (
    ControlPlaneSurface as ControlPlaneSurface,
)
from agentkit.backend.control_plane_http.surface_policy import (
    _enforce_surface_policy,
    _run_request_middleware,
)
from agentkit.backend.control_plane_http.surface_policy import (
    _is_project_scoped_path as _is_project_scoped_path,
)
from agentkit.backend.control_plane_http.takeover_dispatch import (
    TakeoverFrontendDispatcher,
)
from agentkit.backend.control_plane_http.takeover_handlers import (
    dispatch_project_edge_takeover_post,
)
from agentkit.backend.control_plane_http.verify_routes import VerifySystemRoutes

logger = logging.getLogger(__name__)

_WRITER_LEASE_LIVENESS_INTERVAL_SECONDS = 0.1

# Route path patterns (FK-72 §72.8.1) are defined in the sibling ``_route_patterns``
# module (imported at the top of this file) so this module's executed top-level stays
# lean (PY_MODULE_TOP_LEVEL_MAX_LOC_100); they are used under their original names, so
# route matching is unchanged.

_NOT_FOUND_MESSAGE = "Not found"


# ---------------------------------------------------------------------------
# Default-builder helpers (lazy imports)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AG3-091 read-only 405 guard (module-level — no instance state required)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# HttpResponse
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ControlPlaneApplication
# ---------------------------------------------------------------------------


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

    def _resolve_dashboard_service(
        self, dashboard_service: DashboardService | None
    ) -> DashboardService:
        """Return the injected dashboard service or build the default."""
        if dashboard_service is not None:
            return dashboard_service
        from agentkit.backend.bootstrap.composition_root import build_dashboard_service

        return build_dashboard_service(self._story_service)

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
    _StoryDashboardHandlersMixin,
    InstallerDispatchMixin,
    _GovernanceMediationHandlers,
    _GroundedBcDispatchMixin,
    _RuntimeMutationHandlers,
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
        auth_middlewares: Mapping[ControlPlaneSurface, AuthMiddleware] | None = None,
        tenant_scope_middleware: TenantScopeMiddleware | None = None,
        version_handshake_middleware: VersionHandshakeMiddleware | None = None,
        writer_lease_required: bool = True,
    ) -> None:
        r = routes or ControlPlaneApplicationRoutes()
        self._telemetry_service = telemetry_service or ControlPlaneTelemetryService()
        self._guard_counter_service = (
            guard_counter_service or ControlPlaneGuardCounterService()
        )
        self._worker_health_service = (
            worker_health_service or ControlPlaneWorkerHealthService()
        )
        self._runtime_service = runtime_service or _build_default_runtime_service()
        self._story_service = story_service or _build_default_story_service()
        self._dashboard_service = self._resolve_dashboard_service(dashboard_service)
        self._auth_middleware = auth_middleware
        self._auth_middlewares = dict(auth_middlewares or {})
        self._writer_lease_required = writer_lease_required
        self._writer_lease: ControlPlaneWriterLease | None = None
        self._writer_lease_lost = Event()
        self._writer_lease_loss_reason: str | None = None
        # One writer process owns both listeners, so this process-local lock is
        # the atomic project-credential boundary shared by both surfaces. It
        # spans the strategist's "no token exists" authorization check and the
        # installer handler, and also every token create/revoke request. A token
        # therefore cannot appear in the former TOCTOU gap between middleware
        # authorization and privileged installer execution.
        self._project_credential_transition_lock = RLock()
        self._init_default_routes(r, auth_middleware)
        if self._writer_lease_required:
            self._auth_routes.bind_writer_authority(self._assert_writer_authority)
        self._tenant_scope = tenant_scope_middleware or TenantScopeMiddleware()
        # Opt-in like ``auth_middleware``; production wires it ON in
        # ``serve_control_plane`` (FK-91 §91.1a Rule 11). The announced
        # ``/v1/compat`` window is the middleware's, else the central default.
        self._version_handshake = version_handshake_middleware
        self._compat_window: CompatWindow = (
            version_handshake_middleware or VersionHandshakeMiddleware()
        ).window
        self._init_bc_routes(r)

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
        self._takeover_frontend_dispatcher = TakeoverFrontendDispatcher(
            r.takeover_approval_routes or _build_default_takeover_approval_routes(),
            self._telemetry_routes,
        )
        self._third_party_validation_routes = (
            r.third_party_validation_routes
            or _build_default_third_party_validation_routes()
        )
        self._story_split_routes = (
            r.story_split_routes or _build_default_story_split_routes()
        )
        self._story_admin_routes = (
            r.story_admin_routes or _build_default_story_admin_routes()
        )
        self._failure_corpus_routes = (
            r.failure_corpus_routes or _build_default_failure_corpus_routes()
        )
        self._installer_writer_routes = (
            r.installer_writer_routes or _build_default_installer_writer_routes()
        )
        # AG3-241: the verify-system surface (FK-91 §91.1a). It resolves its own
        # filesystem anchor from the canonical project registry, so it needs no
        # service collaborator -- only the seam its tests replace.
        self._verify_system_routes = r.verify_system_routes or VerifySystemRoutes()

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

    def require_productive_writer_lease(self) -> None:
        """Reject every listener application configured without the lease fence."""

        if not self._writer_lease_required:
            raise RuntimeError(
                "a productive control-plane server requires the writer lifetime lease",
            )

    def assert_productive_writer_ready(self) -> None:
        """Prove the startup hook left a held lease before either socket binds."""

        self.require_productive_writer_lease()
        lease = self._writer_lease
        if lease is None:
            raise RuntimeError(
                "control-plane startup completed without an active writer lease",
            )
        lease.assert_held()

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
        if self._writer_lease is not None:
            raise RuntimeError("pre-serve startup may run only once per application")
        self._writer_lease = run_pre_serve_startup(self._runtime_service)

    def release_writer_lease(self) -> None:
        """Quiesce requests/background work, then release the lifetime fence."""

        lease = self._writer_lease
        if lease is not None:
            lease.quiesce_requests()
            if self._writer_lease_loss_reason is None:
                self._third_party_validation_routes.drain_writer_work()
            else:
                self._third_party_validation_routes.abort_writer_work()
            try:
                lease.release()
            finally:
                self._writer_lease = None

    @staticmethod
    def _writer_lease_failure_response(
        correlation_id: str,
        *,
        missing: bool,
    ) -> HttpResponse:
        """Return the fail-closed response for an absent or lost writer lease."""

        error_code = (
            "control_plane_writer_lease_missing"
            if missing
            else "control_plane_writer_lease_lost"
        )
        message = (
            "The control-plane writer lifetime lease is not active"
            if missing
            else "The control-plane writer lifetime lease was lost"
        )
        return _error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            error_code=error_code,
            message=message,
            correlation_id=correlation_id,
        )

    def _handle_request_with_writer_authority(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        request_headers: Mapping[str, str] | None,
        surface: ControlPlaneSurface | None,
        correlation_id: str,
    ) -> HttpResponse:
        """Dispatch one request while its caller owns writer authority."""

        split = urlsplit(path)
        route_path = split.path
        query = parse_qs(split.query)

        if route_path == "/healthz":
            return _handle_healthz(method, correlation_id)

        if (
            method in {"POST", "DELETE"}
            and _route_patterns._PROJECT_CREDENTIAL_TRANSITION_PATH.fullmatch(
                route_path,
            )
            is not None
        ):
            with self._project_credential_transition_lock:
                return self._handle_routed_request(
                    method=method,
                    route_path=route_path,
                    query=query,
                    body=body,
                    request_headers=request_headers,
                    surface=surface,
                    correlation_id=correlation_id,
                )
        return self._handle_routed_request(
            method=method,
            route_path=route_path,
            query=query,
            body=body,
            request_headers=request_headers,
            surface=surface,
            correlation_id=correlation_id,
        )

    def _assert_writer_authority(self) -> None:
        """Verify the productive lease immediately before an external effect."""

        if not self._writer_lease_required:
            return
        lease = self._writer_lease
        if lease is None:
            raise RuntimeError("the control-plane writer lifetime lease is not active")
        lease.assert_held()

    @contextmanager
    def _response_write_scope(self) -> Iterator[None]:
        """Keep the writer lease through the complete HTTP wire response."""

        if not self._writer_lease_required:
            yield
            return
        lease = self._writer_lease
        if lease is None:
            raise ControlPlaneWriterLeaseLostError(
                "the control-plane writer lifetime lease is not active",
            )
        with lease.request_scope():
            yield

    def _record_writer_lease_loss(self, exc: ControlPlaneWriterLeaseLostError) -> None:
        """Mark lease loss as fatal for the shared two-listener runtime."""

        logger.error("Control-plane writer lease lost: %s", exc)
        self._writer_lease_loss_reason = str(exc)
        self._writer_lease_lost.set()
        self._third_party_validation_routes.abort_writer_work()

    def wait_for_writer_lease_loss(self) -> None:
        """Actively prove the reserved PostgreSQL lease session remains live."""

        while not self._writer_lease_lost.wait(
            _WRITER_LEASE_LIVENESS_INTERVAL_SECONDS,
        ):
            lease = self._writer_lease
            if lease is None:
                return
            try:
                lease.assert_held()
            except ControlPlaneWriterLeaseLostError as exc:
                self._record_writer_lease_loss(exc)
                return

    def wake_writer_lease_monitor(self) -> None:
        """Wake the monitor during normal listener-coordinator teardown."""

        self._writer_lease_lost.set()

    @property
    def writer_lease_loss_reason(self) -> str | None:
        """Return the detected fatal lease loss, if any."""

        return self._writer_lease_loss_reason

    def handle_request(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        request_headers: Mapping[str, str] | None = None,
        surface: ControlPlaneSurface | None = None,
    ) -> HttpResponse:
        """Dispatch one HTTP request."""
        correlation_id = _resolve_correlation_id(request_headers)
        if not self._writer_lease_required:
            return self._handle_request_with_writer_authority(
                method=method,
                path=path,
                body=body,
                request_headers=request_headers,
                surface=surface,
                correlation_id=correlation_id,
            )
        lease = self._writer_lease
        if lease is None:
            return self._writer_lease_failure_response(correlation_id, missing=True)
        try:
            with lease.request_scope():
                return self._handle_request_with_writer_authority(
                    method=method,
                    path=path,
                    body=body,
                    request_headers=request_headers,
                    surface=surface,
                    correlation_id=correlation_id,
                )
        except ControlPlaneWriterLeaseLostError as exc:
            self._record_writer_lease_loss(exc)
            return self._writer_lease_failure_response(correlation_id, missing=False)

    def _handle_routed_request(
        self,
        *,
        method: str,
        route_path: str,
        query: dict[str, list[str]],
        body: bytes,
        request_headers: Mapping[str, str] | None,
        surface: ControlPlaneSurface | None,
        correlation_id: str,
    ) -> HttpResponse:
        """Run middleware and dispatch after request-wide transition locking."""

        surface_auth = (
            self._auth_middlewares.get(surface) if surface is not None else None
        )
        middleware_block, auth_result = _run_request_middleware(
            auth_middleware=surface_auth or self._auth_middleware,
            tenant_scope=self._tenant_scope,
            method=method,
            route_path=route_path,
            request_headers=request_headers,
            correlation_id=correlation_id,
        )
        if middleware_block is not None:
            return middleware_block
        surface_block = _enforce_surface_policy(
            surface=surface,
            method=method,
            route_path=route_path,
            auth_result=auth_result,
            correlation_id=correlation_id,
        )
        if surface_block is not None:
            return surface_block

        def _dispatch() -> HttpResponse:
            return self._dispatch_method(
                method,
                route_path,
                query,
                body,
                correlation_id,
                request_headers,
                auth_result,
            )

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

    def _dispatch_method(
        self,
        method: str,
        route_path: str,
        query: dict[str, list[str]],
        body: bytes,
        correlation_id: str,
        request_headers: Mapping[str, str] | None,
        auth_result: AuthResult | None,
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
        takeover_response = self._takeover_frontend_dispatcher.handle(
            method, route_path, query, correlation_id, auth_result,
        )
        if takeover_response is not None:
            return takeover_response
        if method == "GET":
            third_party_response = self._third_party_validation_routes.handle_get(
                route_path, correlation_id,
            )
            if third_party_response is not None:
                return third_party_response
            return self._handle_get_request(route_path, query, correlation_id, auth_result)
        if method == "DELETE":
            return self._handle_delete_request(route_path, body, correlation_id, auth_result)
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
            auth_result,
        )


    def _handle_get_request(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
        auth_result: AuthResult | None,
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

        # AG3-145 Edge-Command-Queue (non-project-scoped, mirrors the sibling
        # project-edge operation/sync/ownership routes):
        commands_match = _route_patterns._EDGE_COMMANDS_COLLECTION_PATTERN.match(route_path)
        if commands_match is not None:
            return _handle_get_open_commands(
                self._runtime_service,
                commands_match.group("run_id"),
                query,
                correlation_id,
            )

        # AG3-147 push-freshness / push-backlog read surface (FK-10 §10.2.4b, AC5):
        freshness_match = _route_patterns._EDGE_PUSH_FRESHNESS_PATTERN.match(route_path)
        if freshness_match is not None:
            return _handle_get_push_freshness(
                self._runtime_service,
                freshness_match.group("run_id"),
                query,
                correlation_id,
            )

        # AG3-147 Edge-Push-Gate bounded online-ownership check (FK-15 §15.5.4, AC6):
        push_ownership_match = _route_patterns._EDGE_PUSH_OWNERSHIP_PATTERN.match(route_path)
        if push_ownership_match is not None:
            return _handle_get_push_ownership(
                self._runtime_service,
                push_ownership_match.group("run_id"),
                query,
                correlation_id,
            )

        # Auth routes (non-project-scoped):
        auth_response = self._auth_routes.handle_get(
            route_path,
            correlation_id,
            auth_result,
        )
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
        installer_response = self._installer_writer_routes.handle_get(
            route_path,
            correlation_id,
            auth_result,
        )
        if installer_response is not None:
            return installer_response

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
        # collisions such as /stories/counters being captured by _route_patterns._PROJECT_STORY_DETAIL.
        rm_response = self._read_model_routes.handle_get(route_path, query, correlation_id)
        if rm_response is not None:
            return _bc_response_to_http_response(rm_response)

        # GET /v1/projects/{key}/stories/search?q=...
        # Must match before /stories/{id} to avoid "search" being treated as story_id.
        story_search_match = _route_patterns._PROJECT_STORY_SEARCH.match(route_path)
        if story_search_match is not None:
            return self._handle_get_story_search(
                story_search_match.group("project_key"), query, correlation_id,
            )

        # GET /v1/projects/{key}/stories (collection)
        stories_match = _route_patterns._PROJECT_STORIES_COLLECTION.match(route_path)
        if stories_match is not None:
            return self._handle_get_stories(stories_match.group("project_key"), correlation_id)

        # GET /v1/projects/{key}/stories/{id}/fields
        # Must match before /stories/{id} (more specific pattern).
        story_fields_match = _route_patterns._PROJECT_STORY_FIELDS.match(route_path)
        if story_fields_match is not None:
            return self._handle_get_story_fields(
                story_fields_match.group("story_id"), correlation_id,
            )

        # GET /v1/projects/{key}/stories/{id}
        story_detail_match = _route_patterns._PROJECT_STORY_DETAIL.match(route_path)
        if story_detail_match is not None:
            return self._handle_get_story(
                story_detail_match.group("story_id"),
                story_detail_match.group("project_key"),
                correlation_id,
            )

        # GET /v1/projects/{key}/dashboard/board
        board_match = _route_patterns._PROJECT_DASHBOARD_BOARD.match(route_path)
        if board_match is not None:
            return self._handle_get_dashboard_board(board_match.group("project_key"), correlation_id)

        # GET /v1/projects/{key}/dashboard/story-metrics
        metrics_match = _route_patterns._PROJECT_DASHBOARD_STORY_METRICS.match(route_path)
        if metrics_match is not None:
            return self._handle_get_dashboard_story_metrics(
                metrics_match.group("project_key"), correlation_id,
            )

        # Grounded BC GET routes (kpi_analytics, task_management; project-scoped):
        bc_get = self._dispatch_new_bc_get(route_path, query, correlation_id)
        if bc_get is not None:
            return bc_get

        # Legacy non-project project-edge operation GET:
        operation_match = _route_patterns._OPERATION_PATH_PATTERN.match(route_path)
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

    def _handle_post_request(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
        request_headers: Mapping[str, str] | None,
        auth_result: AuthResult | None,
    ) -> HttpResponse:
        # AG3-091 read-only endpoints already returned 405 in _dispatch_method
        # (before body decode); this handler only sees genuine mutation paths.
        auth_response = self._auth_routes.handle_post(
            route_path,
            payload,
            correlation_id,
            request_headers,
            auth_result,
        )
        if auth_response is not None:
            return _auth_response_to_http_response(auth_response)

        installer_response = self._dispatch_installer_post(
            route_path, payload, correlation_id, auth_result,
        )
        if installer_response is not None:
            return installer_response

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

        mediation_response = self._dispatch_hook_mediation_post(
            route_path, payload, correlation_id,
        )
        if mediation_response is not None:
            return mediation_response
        project_edge_response = self._dispatch_project_edge_post(
            route_path,
            payload,
            correlation_id,
            auth_result,
        )
        if project_edge_response is not None:
            return project_edge_response

        # AG3-145 Edge-Command-Queue result (non-project-scoped, FK-91 §91.1b):
        command_result_match = _route_patterns._EDGE_COMMAND_RESULT_PATTERN.match(route_path)
        if command_result_match is not None:
            return self._handle_post_command_result(
                command_id=command_result_match.group("command_id"),
                payload=payload,
                correlation_id=correlation_id,
            )

        # AG3-138 admin-abort (non-project-scoped, mirrors the operation GET path):
        admin_abort_match = _route_patterns._OPERATION_ADMIN_ABORT_PATTERN.match(route_path)
        if admin_abort_match is not None:
            return self._handle_post_admin_abort(
                op_id=admin_abort_match.group("op_id"),
                payload=payload,
                correlation_id=correlation_id,
                auth_result=auth_result,
            )

        # Project-scoped story mutations:
        story_post = self._dispatch_project_story_post(
            route_path, payload, correlation_id, auth_result,
        )
        if story_post is not None:
            return story_post

        # Project-scoped phase/closure mutations:
        phase_match = _route_patterns._PROJECT_PHASE_PATH_PATTERN.match(route_path)
        if phase_match is not None:
            return self._handle_post_phase_mutation(
                payload=payload,
                run_id=phase_match.group("run_id"),
                phase=phase_match.group("phase"),
                action=phase_match.group("action"),
                correlation_id=correlation_id,
            )

        closure_match = _route_patterns._PROJECT_CLOSURE_PATH_PATTERN.match(route_path)
        if closure_match is not None:
            return self._handle_post_closure_complete(
                payload=payload,
                run_id=closure_match.group("run_id"),
                correlation_id=correlation_id,
            )

        # Grounded BC POST routes (kpi_analytics, task_management):
        verify_post = self._verify_system_routes.dispatch_post(
            route_path,
            payload,
            correlation_id,
        )
        if verify_post is not None:
            return verify_post

        bc_post = self._dispatch_new_bc_post(
            route_path,
            payload,
            correlation_id,
            auth_result,
        )
        if bc_post is not None:
            return bc_post

        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="not_found",
            message=_NOT_FOUND_MESSAGE,
            correlation_id=correlation_id,
        )

    def _dispatch_project_edge_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> HttpResponse | None:
        takeover_response = dispatch_project_edge_takeover_post(
            route_path=route_path,
            payload=payload,
            correlation_id=correlation_id,
            runtime_service=self._runtime_service,
            auth_result=auth_result,
        )
        if takeover_response is not None:
            return takeover_response
        if route_path == "/v1/project-edge/sync":
            return self._handle_post_project_edge_sync(payload, correlation_id)
        return None

    def _dispatch_project_story_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> HttpResponse | None:
        """Dispatch POST for project-scoped story mutations (AG3-090)."""
        story_split_match = _route_patterns._PROJECT_STORY_SPLIT.match(route_path)
        if story_split_match is not None:
            return self._story_split_routes.handle_post(
                project_key=story_split_match.group("project_key"),
                story_id=story_split_match.group("story_id"),
                payload=payload,
                correlation_id=correlation_id,
                auth_result=auth_result,
            )
        story_reset_match = _route_patterns._PROJECT_STORY_RESET.match(route_path)
        if story_reset_match is not None:
            return self._story_admin_routes.handle_reset(
                project_key=story_reset_match.group("project_key"),
                story_id=story_reset_match.group("story_id"),
                payload=payload,
                correlation_id=correlation_id,
                auth_result=auth_result,
            )
        story_exit_match = _route_patterns._PROJECT_STORY_EXIT.match(route_path)
        if story_exit_match is not None:
            return self._story_admin_routes.handle_exit(
                project_key=story_exit_match.group("project_key"),
                story_id=story_exit_match.group("story_id"),
                payload=payload,
                correlation_id=correlation_id,
                auth_result=auth_result,
            )
        if _route_patterns._PROJECT_STORIES_COLLECTION.match(route_path):
            return self._handle_post_story(payload, correlation_id)

        for pattern, suffix in (
            (_route_patterns._PROJECT_STORY_APPROVE, "approve"),
            (_route_patterns._PROJECT_STORY_REJECT, "reject"),
            (_route_patterns._PROJECT_STORY_CANCEL, "cancel"),
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
        field_match = _route_patterns._PROJECT_STORY_FIELD_KEY.match(route_path)
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
        auth_result: AuthResult | None,
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
            route_path, payload, correlation_id, auth_result,
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
        story_detail_match = _route_patterns._PROJECT_STORY_DETAIL.match(route_path)
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
