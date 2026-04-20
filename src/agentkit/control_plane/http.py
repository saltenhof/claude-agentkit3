"""Minimal HTTP transport for the AgentKit control plane."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPSServer
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.control_plane.models import TelemetryEventIngestRequest
from agentkit.control_plane.telemetry import ControlPlaneTelemetryService

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._telemetry_service = telemetry_service or ControlPlaneTelemetryService()

    def handle_request(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
    ) -> HttpResponse:
        """Dispatch one HTTP request."""

        if path == "/healthz":
            if method != "GET":
                return _json_response(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    {"error": "Method not allowed"},
                    headers=(("Allow", "GET"),),
                )
            return _json_response(HTTPStatus.OK, {"status": "ok"})

        if path != "/v1/telemetry/events":
            return _json_response(
                HTTPStatus.NOT_FOUND,
                {"error": "Not found"},
            )
        if method != "POST":
            return _json_response(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {"error": "Method not allowed"},
                headers=(("Allow", "POST"),),
            )

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _json_response(
                HTTPStatus.BAD_REQUEST,
                {"error": "Request body must be valid JSON"},
            )

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
            return _json_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": str(exc)},
            )

        return _json_response(
            HTTPStatus.CREATED,
            accepted.model_dump(mode="json"),
        )


def serve_control_plane(
    *,
    host: str = "127.0.0.1",
    port: int = 9080,
    certfile: Path,
    keyfile: Path | None = None,
    app: ControlPlaneApplication | None = None,
) -> None:
    """Run the control-plane HTTP server until interrupted."""

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


def _build_handler(
    app: ControlPlaneApplication,
) -> type[BaseHTTPRequestHandler]:
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
