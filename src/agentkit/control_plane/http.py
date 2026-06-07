"""HTTPS transport and routing for the AgentKit control plane."""

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
from agentkit.exceptions import ConfigError
from agentkit.kpi_analytics.dashboard import DashboardService
from agentkit.story.service import StoryService

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from agentkit.auth.http.routes import AuthRouteResponse, AuthRoutes
    from agentkit.auth.middleware import AuthMiddleware
    from agentkit.concept_catalog.http.routes import (
        ConceptCatalogRoutes,
        ConceptRouteResponse,
    )
    from agentkit.execution_planning.http.routes import (
        ExecutionPlanningRouteResponse,
        ExecutionPlanningRoutes,
    )
    from agentkit.multi_llm_hub.http.routes import (
        MultiLlmHubRouteResponse,
        MultiLlmHubRoutes,
    )
    from agentkit.project_management.http.routes import (
        ProjectManagementRoutes,
        ProjectRouteResponse,
    )
    from agentkit.story_context_manager.http.routes import (
        StoryContextRoutes,
        StoryRouteResponse,
    )
    from agentkit.telemetry.http.routes import TelemetryRouteResponse, TelemetryRoutes

logger = logging.getLogger(__name__)

_PHASE_PATH_PATTERN = re.compile(
    r"^/v1/story-runs/(?P<run_id>[^/]+)/phases/(?P<phase>[^/]+)/(?P<action>start|complete|fail)$",
)
_CLOSURE_PATH_PATTERN = re.compile(
    r"^/v1/story-runs/(?P<run_id>[^/]+)/closure/complete$",
)
_OPERATION_PATH_PATTERN = re.compile(
    r"^/v1/project-edge/operations/(?P<op_id>[^/]+)$",
)
_STORY_PATH_PATTERN = re.compile(
    r"^/v1/stories/(?P<story_id>[^/]+)$",
)
_MISSING_PROJECT_KEY_ERROR = "Missing required query parameter: project_key"
_NOT_FOUND_MESSAGE = "Not found"
_CORRELATION_HEADER = "X-Correlation-Id"


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


@dataclass(frozen=True)
class HttpResponse:
    """Serializable HTTP response."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()
    stream: Iterable[bytes] | None = None


class ControlPlaneApplication:
    """Route and validate HTTP requests for the control plane."""

    def __init__(
        self,
        *,
        telemetry_service: ControlPlaneTelemetryService | None = None,
        runtime_service: ControlPlaneRuntimeService | None = None,
        story_service: StoryService | None = None,
        dashboard_service: DashboardService | None = None,
        project_routes: ProjectManagementRoutes | None = None,
        story_routes: StoryContextRoutes | None = None,
        concept_routes: ConceptCatalogRoutes | None = None,
        hub_routes: MultiLlmHubRoutes | None = None,
        planning_routes: ExecutionPlanningRoutes | None = None,
        telemetry_routes: TelemetryRoutes | None = None,
        auth_routes: AuthRoutes | None = None,
        auth_middleware: AuthMiddleware | None = None,
    ) -> None:
        self._telemetry_service = telemetry_service or ControlPlaneTelemetryService()
        self._runtime_service = runtime_service or ControlPlaneRuntimeService()
        self._story_service = story_service or StoryService()
        self._dashboard_service = dashboard_service or DashboardService(
            story_service=self._story_service,
        )
        self._project_routes = project_routes or _build_default_project_routes()
        self._story_routes = story_routes or _build_default_story_routes()
        self._concept_routes = concept_routes or _build_default_concept_routes()
        self._hub_routes = hub_routes or _build_default_hub_routes()
        self._planning_routes = planning_routes or _build_default_planning_routes()
        self._telemetry_routes = telemetry_routes or _build_default_telemetry_routes()
        self._auth_routes = auth_routes or _build_default_auth_routes(auth_middleware)
        self._auth_middleware = auth_middleware

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
            return self._handle_healthz(method, correlation_id)

        if self._auth_middleware is not None:
            auth_result = self._auth_middleware.authorize(
                method=method,
                route_path=route_path,
                request_headers=request_headers,
                correlation_id=correlation_id,
            )
            if isinstance(auth_result, AuthMiddlewareResponse):
                return _auth_middleware_response_to_http_response(auth_result)

        if method == "GET":
            return self._handle_get_request(route_path, query, correlation_id)

        if method == "DELETE":
            return self._handle_delete_request(route_path, correlation_id)

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

    def _handle_healthz(self, method: str, correlation_id: str) -> HttpResponse:
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

    def _handle_get_request(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse:
        auth_response = self._auth_routes.handle_get(route_path, correlation_id)
        if auth_response is not None:
            return _auth_response_to_http_response(auth_response)

        concept_response = self._concept_routes.handle_get(
            route_path,
            query,
            correlation_id,
        )
        if concept_response is not None:
            return _concept_response_to_http_response(concept_response)

        telemetry_response = self._telemetry_routes.handle_get(
            route_path,
            query,
            correlation_id,
        )
        if telemetry_response is not None:
            return _telemetry_response_to_http_response(telemetry_response)

        hub_response = self._hub_routes.handle_get(route_path, query, correlation_id)
        if hub_response is not None:
            return _hub_response_to_http_response(hub_response)

        planning_response = self._planning_routes.handle_get(
            route_path,
            correlation_id,
        )
        if planning_response is not None:
            return _planning_response_to_http_response(planning_response)

        project_response = self._project_routes.handle_get(
            route_path,
            query,
            correlation_id,
        )
        if project_response is not None:
            return _project_response_to_http_response(project_response)

        story_response = self._story_routes.handle_get(route_path, correlation_id, query)
        if story_response is not None:
            return _story_response_to_http_response(story_response)

        if route_path == "/v1/stories":
            return self._handle_get_stories(query, correlation_id)
        if route_path == "/v1/dashboard/board":
            return self._handle_get_dashboard_board(query, correlation_id)
        if route_path == "/v1/dashboard/story-metrics":
            return self._handle_get_dashboard_story_metrics(query, correlation_id)

        story_match = _STORY_PATH_PATTERN.match(route_path)
        if story_match is not None:
            return self._handle_get_story(
                story_match.group("story_id"),
                query,
                correlation_id,
            )

        operation_match = _OPERATION_PATH_PATTERN.match(route_path)
        if operation_match is not None:
            return self._handle_get_operation(
                operation_match.group("op_id"),
                correlation_id,
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
    ) -> HttpResponse:
        auth_response = self._auth_routes.handle_post(
            route_path,
            payload,
            correlation_id,
            request_headers,
        )
        if auth_response is not None:
            return _auth_response_to_http_response(auth_response)

        project_response = self._project_routes.handle_post(
            route_path,
            payload,
            correlation_id,
        )
        if project_response is not None:
            return _project_response_to_http_response(project_response)

        story_response = self._story_routes.handle_post(
            route_path,
            payload,
            correlation_id,
        )
        if story_response is not None:
            return _story_response_to_http_response(story_response)

        hub_response = self._hub_routes.handle_post(
            route_path,
            payload,
            correlation_id,
        )
        if hub_response is not None:
            return _hub_response_to_http_response(hub_response)

        planning_response = self._planning_routes.handle_post(
            route_path,
            payload,
            correlation_id,
        )
        if planning_response is not None:
            return _planning_response_to_http_response(planning_response)

        if route_path == "/v1/telemetry/events":
            return self._handle_post_telemetry(payload, correlation_id)
        if route_path == "/v1/project-edge/sync":
            return self._handle_post_project_edge_sync(payload, correlation_id)

        phase_match = _PHASE_PATH_PATTERN.match(route_path)
        if phase_match is not None:
            return self._handle_post_phase_mutation(
                payload=payload,
                run_id=phase_match.group("run_id"),
                phase=phase_match.group("phase"),
                action=phase_match.group("action"),
                correlation_id=correlation_id,
            )

        closure_match = _CLOSURE_PATH_PATTERN.match(route_path)
        if closure_match is not None:
            return self._handle_post_closure_complete(
                payload=payload,
                run_id=closure_match.group("run_id"),
                correlation_id=correlation_id,
            )
        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="not_found",
            message=_NOT_FOUND_MESSAGE,
            correlation_id=correlation_id,
        )

    def _handle_put_request(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        planning_response = self._planning_routes.handle_put(
            route_path,
            payload,
            correlation_id,
        )
        if planning_response is not None:
            return _planning_response_to_http_response(planning_response)

        story_response = self._story_routes.handle_put(
            route_path,
            payload,
            correlation_id,
        )
        if story_response is not None:
            return _story_response_to_http_response(story_response)

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
        auth_response = self._auth_routes.handle_delete(
            route_path,
            {},
            correlation_id,
        )
        if auth_response is not None:
            return _auth_response_to_http_response(auth_response)

        planning_response = self._planning_routes.handle_delete(
            route_path,
            correlation_id,
        )
        if planning_response is not None:
            return _planning_response_to_http_response(planning_response)
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
        project_response = self._project_routes.handle_patch(
            route_path,
            payload,
            correlation_id,
        )
        if project_response is not None:
            return _project_response_to_http_response(project_response)

        story_response = self._story_routes.handle_patch(
            route_path,
            payload,
            correlation_id,
        )
        if story_response is not None:
            return _story_response_to_http_response(story_response)

        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="not_found",
            message=_NOT_FOUND_MESSAGE,
            correlation_id=correlation_id,
        )

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
        # AG3-054 (FK-20 §20.8.2): a fail-closed REJECTED start (pre-start-guard
        # denial / invalid first-call / illegal transition) materialized NO run
        # state. It must NOT be reported as a 201 CREATED success (which would
        # imply the run was admitted/started); surface it as 409 Conflict so the
        # caller never treats the run as activated. ``edge_bundle`` is ``None`` on
        # a rejection -- the serializer handles it; the rejection detail travels
        # on ``phase_dispatch``.
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

    def _handle_get_operation(
        self,
        op_id: str,
        correlation_id: str,
    ) -> HttpResponse:
        try:
            result = self._runtime_service.get_operation(op_id)
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

    def _handle_get_stories(
        self,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse:
        project_key = _single_query_value(query, "project_key")
        if project_key is None:
            return _missing_project_key_response(correlation_id)
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

    def _handle_get_story(
        self,
        story_id: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse:
        project_key = _single_query_value(query, "project_key")
        if project_key is None:
            return _missing_project_key_response(correlation_id)
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

    def _handle_get_dashboard_board(
        self,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse:
        project_key = _single_query_value(query, "project_key")
        if project_key is None:
            return _missing_project_key_response(correlation_id)
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
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse:
        project_key = _single_query_value(query, "project_key")
        if project_key is None:
            return _missing_project_key_response(correlation_id)
        try:
            result = self._dashboard_service.get_story_metrics(project_key)
        except RuntimeError as exc:
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
    """Map a backend-requirement ``ConfigError`` to a structured 503 (AG3-054 #4).

    The Postgres gate (``_require_postgres_backend_on_first_use``) raises
    ``ConfigError`` (a subclass of ``AgentKitError``, NOT ``RuntimeError``) when
    the control-plane store is unavailable. Without an explicit catch it would
    escape the handler as an uncaught 500. The control plane is a backend
    requirement, so it surfaces as a 503 Service Unavailable with a clear body and
    a stable ``error_code`` (FK-22 §22.9; fail-closed but a structured response).
    """
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


def _single_query_value(
    query: dict[str, list[str]],
    key: str,
) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _missing_project_key_response(correlation_id: str) -> HttpResponse:
    return _error_response(
        HTTPStatus.BAD_REQUEST,
        error_code="missing_project_key",
        message=_MISSING_PROJECT_KEY_ERROR,
        correlation_id=correlation_id,
    )


def _resolve_correlation_id(request_headers: Mapping[str, str] | None) -> str:
    if request_headers is not None:
        provided = request_headers.get(_CORRELATION_HEADER)
        if provided is not None:
            value = provided.strip()
            if value:
                return value
    return f"req-{uuid.uuid4().hex}"


def _has_header(headers: Sequence[tuple[str, str]], name: str) -> bool:
    normalized = name.lower()
    return any(key.lower() == normalized for key, _value in headers)
