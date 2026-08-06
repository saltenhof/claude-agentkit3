"""``BaseHTTPRequestHandler`` adapter for the control-plane application.

This module owns exactly one translation: ONE socket exchange becomes ONE
:class:`HttpResponse` on the wire. It is deliberately separate from routing
(``app.py``) and from listener lifetime (``server.py``) because its
correctness question is neither -- it is *when the writer authority is
re-checked while bytes are already leaving the process*, and what a lease loss
mid-response is allowed to send instead.

Extracted from ``app.py`` (AG3-229) as a pure structural move.
"""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.writer_lease import ControlPlaneWriterLeaseLostError
from agentkit.backend.control_plane_http.responses import (
    _has_header,
    _resolve_correlation_id,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane_http.app import ControlPlaneApplication
    from agentkit.backend.control_plane_http.responses import HttpResponse
    from agentkit.backend.control_plane_http.surface_policy import ControlPlaneSurface

logger = logging.getLogger(__name__)


class _ResponseWriteState:
    """Track whether response headers have reached the socket."""

    def __init__(self) -> None:
        self.started = False


def _write_handler_response(
    handler: BaseHTTPRequestHandler,
    app: ControlPlaneApplication,
    response: HttpResponse,
    state: _ResponseWriteState,
    *,
    fence_writer: bool,
) -> None:
    """Write one complete response while checking writer authority at wire edges."""

    if fence_writer:
        app._assert_writer_authority()
    handler.send_response(response.status_code)
    for key, value in response.headers:
        handler.send_header(key, value)
    if not _has_header(response.headers, "Content-Type"):
        handler.send_header("Content-Type", "application/json")
    if response.stream is None:
        handler.send_header("Content-Length", str(len(response.body)))
        if fence_writer:
            app._assert_writer_authority()
        handler.end_headers()
        state.started = True
        if fence_writer:
            app._assert_writer_authority()
        handler.wfile.write(response.body)
        return
    if fence_writer:
        app._assert_writer_authority()
    handler.end_headers()
    state.started = True
    for chunk in response.stream:
        if fence_writer:
            app._assert_writer_authority()
        handler.wfile.write(chunk)
        handler.wfile.flush()


def _handle_http_exchange(
    handler: BaseHTTPRequestHandler,
    app: ControlPlaneApplication,
    surface: ControlPlaneSurface | None,
    body: bytes,
) -> None:
    """Fence application dispatch and the complete response as one request."""

    request_headers = dict(handler.headers.items())
    state = _ResponseWriteState()
    try:
        with app._response_write_scope():
            response = app.handle_request(
                method=handler.command,
                path=handler.path,
                body=body,
                request_headers=request_headers,
                surface=surface,
            )
            _write_handler_response(handler, app, response, state, fence_writer=True)
    except ControlPlaneWriterLeaseLostError as exc:
        app._record_writer_lease_loss(exc)
        handler.close_connection = True
        if not state.started:
            # Status/headers may have been buffered but not sent. Discard them
            # before writing the fail-closed response.
            handler.__dict__["_headers_buffer"] = []
            failure = app._writer_lease_failure_response(
                _resolve_correlation_id(request_headers),
                missing=False,
            )
            _write_handler_response(handler, app, failure, state, fence_writer=False)


def _build_handler(
    app: ControlPlaneApplication,
    surface: ControlPlaneSurface | None = None,
) -> type[BaseHTTPRequestHandler]:
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
            _handle_http_exchange(self, app, surface, body)

        def log_message(self, message_format: str, *args: object) -> None:
            logger.info("control-plane %s", message_format % args)

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            super().log_request(code, size)

    return ControlPlaneHandler
