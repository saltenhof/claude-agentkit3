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

from agentkit.control_plane.models import (
    ApiErrorResponse,
    ClosureCompleteRequest,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
    TelemetryEventIngestRequest,
)
from agentkit.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.control_plane.telemetry import ControlPlaneTelemetryService
from agentkit.dashboard import DashboardService
from agentkit.story.service import StoryService

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

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
_CORRELATION_HEADER = "X-Correlation-Id"


@dataclass(frozen=True)
class HttpResponse:
    """Serializable HTTP response."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


class ControlPlaneApplication:
    """Route and validate HTTP requests for the control plane."""

    def __init__(
        self,
        *,
        telemetry_service: ControlPlaneTelemetryService | None = None,
        runtime_service: ControlPlaneRuntimeService | None = None,
        story_service: StoryService | None = None,
        dashboard_service: DashboardService | None = None,
    ) -> None:
        self._telemetry_service = telemetry_service or ControlPlaneTelemetryService()
        self._runtime_service = runtime_service or ControlPlaneRuntimeService()
        self._story_service = story_service or StoryService()
        self._dashboard_service = dashboard_service or DashboardService(
            story_service=self._story_service,
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
            return self._handle_healthz(method, correlation_id)

        if method == "GET":
            return self._handle_get_request(route_path, query, correlation_id)

        payload = _decode_json_body(body, correlation_id)
        if isinstance(payload, HttpResponse):
            return payload
        return self._handle_post_request(route_path, payload, correlation_id)

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
            message="Not found",
            correlation_id=correlation_id,
        )

    def _handle_post_request(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
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
            message="Not found",
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
        except RuntimeError as exc:
            logger.warning("Control-plane phase mutation unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="phase_mutation_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.CREATED,
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

    application = app or ControlPlaneApplication()
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
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            self.wfile.write(response.body)

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
