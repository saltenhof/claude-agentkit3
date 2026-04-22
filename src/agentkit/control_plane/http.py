"""HTTPS transport and routing for the AgentKit control plane."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPSServer
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from agentkit.control_plane.models import (
    ClosureCompleteRequest,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
    TelemetryEventIngestRequest,
)
from agentkit.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.control_plane.telemetry import ControlPlaneTelemetryService
from agentkit.story.service import StoryService

if TYPE_CHECKING:
    from collections.abc import Sequence
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
    ) -> None:
        self._telemetry_service = telemetry_service or ControlPlaneTelemetryService()
        self._runtime_service = runtime_service or ControlPlaneRuntimeService()
        self._story_service = story_service or StoryService()

    def handle_request(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
    ) -> HttpResponse:
        """Dispatch one HTTP request."""
        split = urlsplit(path)
        route_path = split.path
        query = parse_qs(split.query)

        if route_path == "/healthz":
            if method != "GET":
                return _json_response(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    {"error": "Method not allowed"},
                    headers=(("Allow", "GET"),),
                )
            return _json_response(HTTPStatus.OK, {"status": "ok"})

        if method == "GET":
            if route_path == "/v1/stories":
                return self._handle_get_stories(query)

            story_match = _STORY_PATH_PATTERN.match(route_path)
            if story_match is not None:
                return self._handle_get_story(story_match.group("story_id"), query)

            operation_match = _OPERATION_PATH_PATTERN.match(route_path)
            if operation_match is not None:
                return self._handle_get_operation(operation_match.group("op_id"))
            return _json_response(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _json_response(
                HTTPStatus.BAD_REQUEST,
                {"error": "Request body must be valid JSON"},
            )

        if route_path == "/v1/telemetry/events":
            return self._handle_post_telemetry(payload)

        if route_path == "/v1/project-edge/sync":
            return self._handle_post_project_edge_sync(payload)

        phase_match = _PHASE_PATH_PATTERN.match(route_path)
        if phase_match is not None:
            return self._handle_post_phase_mutation(
                payload=payload,
                run_id=phase_match.group("run_id"),
                phase=phase_match.group("phase"),
                action=phase_match.group("action"),
            )

        closure_match = _CLOSURE_PATH_PATTERN.match(route_path)
        if closure_match is not None:
            return self._handle_post_closure_complete(
                payload=payload,
                run_id=closure_match.group("run_id"),
            )

        return _json_response(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def _handle_post_telemetry(self, payload: object) -> HttpResponse:
        try:
            request = TelemetryEventIngestRequest.model_validate(payload)
            accepted = self._telemetry_service.ingest_event(request)
        except ValidationError as exc:
            return _json_response(
                HTTPStatus.BAD_REQUEST,
                {"error": "Invalid telemetry event payload", "detail": exc.errors()},
            )
        except RuntimeError as exc:
            logger.warning("Control-plane telemetry ingest unavailable: %s", exc)
            return _json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        return _json_response(HTTPStatus.CREATED, accepted.model_dump(mode="json"))

    def _handle_post_phase_mutation(
        self,
        *,
        payload: object,
        run_id: str,
        phase: str,
        action: str,
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
            return _json_response(
                HTTPStatus.BAD_REQUEST,
                {"error": "Invalid phase mutation payload", "detail": exc.errors()},
            )
        except RuntimeError as exc:
            logger.warning("Control-plane phase mutation unavailable: %s", exc)
            return _json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        return _json_response(HTTPStatus.CREATED, result.model_dump(mode="json"))

    def _handle_post_closure_complete(
        self,
        *,
        payload: object,
        run_id: str,
    ) -> HttpResponse:
        try:
            request = ClosureCompleteRequest.model_validate(payload)
            result = self._runtime_service.complete_closure(
                run_id=run_id,
                request=request,
            )
        except ValidationError as exc:
            return _json_response(
                HTTPStatus.BAD_REQUEST,
                {"error": "Invalid closure payload", "detail": exc.errors()},
            )
        except RuntimeError as exc:
            logger.warning("Control-plane closure unavailable: %s", exc)
            return _json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        return _json_response(HTTPStatus.CREATED, result.model_dump(mode="json"))

    def _handle_post_project_edge_sync(self, payload: object) -> HttpResponse:
        try:
            request = ProjectEdgeSyncRequest.model_validate(payload)
            result = self._runtime_service.sync_project_edge(request)
        except ValidationError as exc:
            return _json_response(
                HTTPStatus.BAD_REQUEST,
                {"error": "Invalid project-edge sync payload", "detail": exc.errors()},
            )
        except RuntimeError as exc:
            logger.warning("Project-edge sync unavailable: %s", exc)
            return _json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        return _json_response(HTTPStatus.OK, result.model_dump(mode="json"))

    def _handle_get_operation(self, op_id: str) -> HttpResponse:
        try:
            result = self._runtime_service.get_operation(op_id)
        except RuntimeError as exc:
            logger.warning("Project-edge reconcile unavailable: %s", exc)
            return _json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        if result is None:
            return _json_response(
                HTTPStatus.NOT_FOUND,
                {"error": "Operation not found"},
            )
        return _json_response(HTTPStatus.OK, result.model_dump(mode="json"))

    def _handle_get_stories(
        self,
        query: dict[str, list[str]],
    ) -> HttpResponse:
        project_key = _single_query_value(query, "project_key")
        if project_key is None:
            return _json_response(
                HTTPStatus.BAD_REQUEST,
                {"error": "Missing required query parameter: project_key"},
            )
        try:
            result = self._story_service.list_stories(project_key)
        except RuntimeError as exc:
            logger.warning("Story list unavailable: %s", exc)
            return _json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        return _json_response(HTTPStatus.OK, result.model_dump(mode="json"))

    def _handle_get_story(
        self,
        story_id: str,
        query: dict[str, list[str]],
    ) -> HttpResponse:
        project_key = _single_query_value(query, "project_key")
        if project_key is None:
            return _json_response(
                HTTPStatus.BAD_REQUEST,
                {"error": "Missing required query parameter: project_key"},
            )
        try:
            result = self._story_service.get_story(project_key, story_id)
        except RuntimeError as exc:
            logger.warning("Story detail unavailable: %s", exc)
            return _json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        if result is None:
            return _json_response(HTTPStatus.NOT_FOUND, {"error": "Story not found"})
        return _json_response(HTTPStatus.OK, result.model_dump(mode="json"))


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
    headers: Sequence[tuple[str, str]] = (),
) -> HttpResponse:
    return HttpResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=tuple(headers),
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
