"""Listener lifetime of the control-plane writer process (FK-72 §72.8.2).

Owns what exists once per PROCESS rather than once per request: the exclusive
HTTPS listener sockets, the productive composition of the application, the
pre-serve startup sequence, and the coupled shutdown of both surfaces. Routing
lives in ``app.py``, the socket-to-response translation in ``wire_adapter.py``;
neither of them may decide when a listener starts or stops.

Extracted from ``app.py`` (AG3-229) as a pure structural move.
"""

from __future__ import annotations

import logging
import socket
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from http.server import ThreadingHTTPSServer as _ThreadingHTTPSServer
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.writer_lease import ControlPlaneWriterLeaseLostError
from agentkit.backend.control_plane_http.app import ControlPlaneApplication
from agentkit.backend.control_plane_http.routes_config import (
    ControlPlaneApplicationRoutes,
)
from agentkit.backend.control_plane_http.surface_policy import ControlPlaneSurface
from agentkit.backend.control_plane_http.version_handshake import (
    VersionHandshakeMiddleware,
)
from agentkit.backend.control_plane_http.wire_adapter import _build_handler

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)


class ThreadingHTTPSServer(_ThreadingHTTPSServer):
    """HTTPS server whose listener address cannot be shared with another process."""

    # On Windows SO_REUSEADDR permits unrelated processes to bind the same
    # address, making requests nondeterministically reach the wrong security
    # surface. Listener ownership is exclusive for the whole writer lifetime.
    allow_reuse_address = False
    daemon_threads = False
    block_on_close = True

    def server_bind(self) -> None:
        """Bind with OS-enforced exclusivity before accepting any request."""

        exclusive_option = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive_option is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive_option, 1)
        super().server_bind()


def serve_control_plane(
    *,
    ui_host: str,
    ui_port: int,
    project_api_host: str,
    project_api_port: int,
    certfile: Path,
    keyfile: Path | None = None,
    app: ControlPlaneApplication | None = None,
    startup_hook: Callable[[ControlPlaneApplication], None] | None = None,
) -> None:
    """Run both HTTPS surfaces in one writer process until interrupted.

    Both listener coordinates are mandatory and carry no defaults: the listener
    does not own the port registry.  UI-BFF and Project-API share this exact
    application, boot identity, startup reconciliation and lifetime writer
    lease; only their bind coordinates and per-surface security policy differ.

    AG3-138 IMPL-003: the productive startup (lease acquisition, instance
    identity, reconciliation) always runs BETWEEN application construction and
    ``serve_forever()``. ``startup_hook`` is an optional pre-start observer or
    fault-injection seam; it cannot replace the productive startup sequence.
    """

    if (ui_host, ui_port) == (project_api_host, project_api_port):
        raise ValueError("UI-BFF and Project-API listeners require distinct bind addresses")
    application = _build_production_application() if app is None else app
    # GUARANTEE the real listener is handshake-gated even when an app was injected
    # without a handshake middleware (close the fail-OPEN path; FK-91 Rule 11).
    application.ensure_version_handshake()
    application.require_productive_writer_lease()
    # AG3-138 IMPL-003: the pre-serve startup hook runs BEFORE the socket is bound
    # and BEFORE ``serve_forever()`` -- so the listener accepts its first request
    # only after instance-identity resolution + orphan reconciliation succeed. A
    # failure here (fail-closed, AC9) propagates uncaught: the server never starts
    # with an unclear claim inventory.
    servers: list[ThreadingHTTPSServer] = []
    try:
        if startup_hook is not None:
            startup_hook(application)
        # Call the concrete boundary implementation, not an injected override:
        # an arbitrary application/hook may not substitute a duck-typed lease
        # for the mandatory PostgreSQL session acquisition.
        ControlPlaneApplication.run_pre_serve_startup_hook(application)
        application.assert_productive_writer_ready()
        servers.append(
            ThreadingHTTPSServer(
                (ui_host, ui_port),
                _build_handler(application, ControlPlaneSurface.UI_BFF),
                certfile=str(certfile),
                keyfile=str(keyfile) if keyfile is not None else None,
            ),
        )
        servers.append(
            ThreadingHTTPSServer(
                (project_api_host, project_api_port),
                _build_handler(application, ControlPlaneSurface.PROJECT_API),
                certfile=str(certfile),
                keyfile=str(keyfile) if keyfile is not None else None,
            ),
        )
        logger.info(
            "Starting AgentKit UI-BFF on https://%s:%d and Project-API on "
            "https://%s:%d using %s",
            ui_host,
            ui_port,
            project_api_host,
            project_api_port,
            certfile,
        )
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="agentkit-listener") as pool:
            server_futures = tuple(pool.submit(server.serve_forever) for server in servers)
            monitor_future = pool.submit(application.wait_for_writer_lease_loss)
            futures = (*server_futures, monitor_future)
            try:
                done, pending = wait(futures, return_when=FIRST_COMPLETED)
            except BaseException:
                # ``ThreadPoolExecutor.__exit__`` waits for its workers.  Stop
                # both serve loops before leaving the context on Ctrl+C or any
                # coordinator failure, otherwise shutdown would deadlock.
                for server in servers:
                    server.shutdown()
                application.wake_writer_lease_monitor()
                raise
            # Either surface ending tears down the whole writer runtime.  Keeping
            # one surface alive after its sibling failed would silently change
            # the advertised security topology.
            for server, future in zip(servers, server_futures, strict=True):
                if future in pending:
                    server.shutdown()
            application.wake_writer_lease_monitor()
            for future in done | pending:
                future.result()
            if application.writer_lease_loss_reason is not None:
                raise ControlPlaneWriterLeaseLostError(
                    application.writer_lease_loss_reason,
                )
    finally:
        for server in servers:
            server.server_close()
        application.release_writer_lease()


def _build_production_application() -> ControlPlaneApplication:
    """Build one runtime with separate listener auth contexts and shared owners."""
    from agentkit.backend.auth.credentials import StrategistCredentialStore
    from agentkit.backend.auth.http.routes import AuthRoutes
    from agentkit.backend.auth.middleware import AuthMiddleware
    from agentkit.backend.auth.sessions import FileSessionStore

    credential_store = StrategistCredentialStore()
    session_store = FileSessionStore(credential_store)
    ui_auth = AuthMiddleware(session_store=session_store)
    project_auth = AuthMiddleware(
        session_store=session_store,
        token_repository=ui_auth.token_repository,
    )
    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            auth_routes=AuthRoutes(
                credential_store=credential_store,
                session_store=session_store,
                token_repository=ui_auth.token_repository,
            ),
        ),
        auth_middleware=ui_auth,
        auth_middlewares={
            ControlPlaneSurface.UI_BFF: ui_auth,
            ControlPlaneSurface.PROJECT_API: project_auth,
        },
        version_handshake_middleware=VersionHandshakeMiddleware(),
        writer_lease_required=True,
    )
