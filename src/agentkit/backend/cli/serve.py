"""Level-1 Core bootstrap: the single serve implementation + UI provisioning.

FK-10 §10.2.5 / §10.7.2-§10.7.4 define the Core bootstrap verbs of installation
level 1 (the central core). The AK3 backend is **one** writer process with two
HTTPS listeners: UI-BFF and Project-API. They share one application, boot
identity and startup reconciliation. There is therefore exactly **one** serve
implementation (:func:`run_serve`) and exactly one writer lifecycle.

``agentkit ui`` provisions the SPA frontend (a static bundle), a
distinct artifact from the backend listener; it never provisions Postgres nor
runs DB migrations (those are ops-driven, §10.2.5).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.boundary.network import LoopbackBindHostError, ensure_loopback_bind_host
from agentkit.backend.config.defaults import (
    CORE_PROJECT_API_PORT,
    CORE_UI_BFF_PORT,
    CORE_UI_PORT,
)

if TYPE_CHECKING:
    from http.server import SimpleHTTPRequestHandler


class ServeFn(Protocol):
    """The control-plane listener entrypoint (one shared implementation)."""

    def __call__(
        self,
        *,
        ui_host: str,
        ui_port: int,
        project_api_host: str,
        project_api_port: int,
        certfile: Path,
        keyfile: Path | None,
    ) -> None: ...


class UiServeFn(Protocol):
    """The SPA static-bundle server entrypoint."""

    def __call__(self, *, host: str, port: int, dist_dir: Path) -> None: ...


def run_serve(
    *,
    ui_host: str,
    project_api_host: str,
    certfile: Path,
    keyfile: Path | None,
    ui_port: int | None = None,
    project_api_port: int | None = None,
    serve_fn: ServeFn | None = None,
) -> int:
    """Run UI-BFF and Project-API in the one Core writer process.

    Args:
        ui_host: Bind host for the UI-BFF surface.
        project_api_host: Bind host for the Project-API surface.
        certfile: The TLS certificate path (the listener is HTTPS, fail-closed).
        keyfile: The optional TLS key path.
        ui_port: UI-BFF port override; defaults to the central port registry.
        project_api_port: Project-API port override; defaults likewise.
        serve_fn: Injection seam for the control-plane entrypoint (tests assert
            delegation without binding a socket); defaults to the productive
            ``serve_control_plane``.

    Returns:
        Process exit code (0 on a clean shutdown).
    """
    resolved_serve = serve_fn if serve_fn is not None else _default_serve_fn()
    resolved_serve(
        ui_host=ui_host,
        ui_port=CORE_UI_BFF_PORT if ui_port is None else ui_port,
        project_api_host=project_api_host,
        project_api_port=(
            CORE_PROJECT_API_PORT if project_api_port is None else project_api_port
        ),
        certfile=certfile,
        keyfile=keyfile,
    )
    return 0


def run_ui(
    *,
    host: str,
    port: int | None = None,
    dist_dir: Path | None = None,
    serve_fn: UiServeFn | None = None,
) -> int:
    """Provision the SPA frontend (``agentkit ui``, FK-10 §10.2.5).

    Serves the bundled SPA ``dist/`` as static files (with SPA index fallback).
    FAIL-CLOSED: a missing bundle is a non-zero exit, never a silent no-op.

    Args:
        host: The bind host.
        port: An explicit port override; defaults to :data:`CORE_UI_PORT`.
        dist_dir: The SPA bundle directory; defaults to the packaged bundle.
        serve_fn: Injection seam for the static server (tests assert wiring
            without binding a socket); defaults to the productive SPA server.

    Returns:
        Process exit code (0 on a clean shutdown, 1 when the bundle is absent).
    """
    resolved_dist = dist_dir if dist_dir is not None else default_ui_dist_dir()
    if not resolved_dist.is_dir():
        print(
            "agentkit ui failed [UiBundleMissing]: the SPA bundle was not found "
            f"at {resolved_dist}. Build the frontend before serving it.",
            file=sys.stderr,
        )
        return 1
    resolved_port = port if port is not None else CORE_UI_PORT
    runner = serve_fn if serve_fn is not None else _default_ui_serve_fn()
    runner(host=host, port=resolved_port, dist_dir=resolved_dist)
    return 0


def default_ui_dist_dir() -> Path:
    """Return the packaged SPA bundle directory (``frontend/app/dist``)."""
    import agentkit

    return Path(agentkit.__file__).resolve().parent / "frontend" / "app" / "dist"


def _default_serve_fn() -> ServeFn:
    """Resolve the productive control-plane listener at call time.

    Imported lazily so a test ``monkeypatch`` of
    ``agentkit.backend.control_plane.http.serve_control_plane`` is honoured and
    the heavy HTTP stack is not imported for an unrelated command.
    """
    from agentkit.backend.control_plane.http import serve_control_plane

    return serve_control_plane


def _default_ui_serve_fn() -> UiServeFn:
    """Resolve the productive SPA static server."""
    return _serve_spa


def _serve_spa(*, host: str, port: int, dist_dir: Path) -> None:
    """Serve ``dist_dir`` as a static SPA (index fallback) until interrupted."""
    from http.server import ThreadingHTTPServer

    _ensure_spa_loopback_host(host)
    handler = _build_spa_handler(dist_dir)
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _ensure_spa_loopback_host(host: str) -> None:
    """Reject cleartext SPA binds that resolve outside the loopback interface."""
    try:
        ensure_loopback_bind_host(host)
    except LoopbackBindHostError as exc:
        raise LoopbackBindHostError(
            "agentkit ui serves cleartext HTTP and is restricted to loopback; "
            f"{exc}",
        ) from exc


def _build_spa_handler(dist_dir: Path) -> type[SimpleHTTPRequestHandler]:
    """Build a static handler rooted at ``dist_dir`` with SPA index fallback."""
    from http.server import SimpleHTTPRequestHandler

    root = str(dist_dir)

    class _SpaHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=root, **kwargs)  # type: ignore[arg-type]

        def send_head(self):  # type: ignore[no-untyped-def] # stdlib override
            path = self.translate_path(self.path)
            if not Path(path).exists():
                # SPA client-side routing: unknown paths fall back to index.html.
                self.path = "/index.html"
            return super().send_head()

    return _SpaHandler


__all__ = [
    "ServeFn",
    "LoopbackBindHostError",
    "UiServeFn",
    "default_ui_dist_dir",
    "run_serve",
    "run_ui",
]
