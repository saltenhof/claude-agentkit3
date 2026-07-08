"""Level-1 Core bootstrap: the single serve implementation + UI provisioning.

FK-10 §10.2.5 / §10.7.2-§10.7.4 define the Core bootstrap verbs of installation
level 1 (the central core). The AK3 backend is **one** server process (FK-72
§72.8); the ``--ui-bff`` (port 9701) and ``--project-api`` (port 9702) profiles
are the same control-plane listener bound to a profile-specific default port.
There is therefore exactly **one** serve implementation (:func:`run_serve`); the
retired ``serve-control-plane`` verb is a compat alias that delegates to
``run_serve`` with the :data:`ServeProfile.PROJECT_API` profile (no second
transport path — FIX THE MODEL).

``agentkit ui`` (port 9700) provisions the SPA frontend (a static bundle), a
distinct artifact from the backend listener; it never provisions Postgres nor
runs DB migrations (those are ops-driven, §10.2.5).
"""

from __future__ import annotations

import ipaddress
import socket
import sys
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from http.server import SimpleHTTPRequestHandler

#: Default SPA (UI) port (FK-10 §10.7.2: ``agentkit ui``).
UI_PORT = 9700
#: Default UI-BFF backend port (FK-10 §10.7.2: ``agentkit serve --ui-bff``).
UI_BFF_PORT = 9701
#: Default Project-API backend port (FK-10 §10.7.2: ``agentkit serve --project-api``).
PROJECT_API_PORT = 9702


class ServeProfile(Enum):
    """Backend serve profile of the Core listener (FK-10 §10.7.2/§10.7.4)."""

    UI_BFF = "ui-bff"
    PROJECT_API = "project-api"


_PROFILE_DEFAULT_PORTS: dict[ServeProfile, int] = {
    ServeProfile.UI_BFF: UI_BFF_PORT,
    ServeProfile.PROJECT_API: PROJECT_API_PORT,
}


class ServeFn(Protocol):
    """The control-plane listener entrypoint (one shared implementation)."""

    def __call__(
        self, *, host: str, port: int, certfile: Path, keyfile: Path | None
    ) -> None: ...


class UiServeFn(Protocol):
    """The SPA static-bundle server entrypoint."""

    def __call__(self, *, host: str, port: int, dist_dir: Path) -> None: ...


class UiBindHostError(ValueError):
    """Raised when the cleartext SPA server is asked to bind outside loopback."""


def resolve_serve_port(profile: ServeProfile, explicit_port: int | None) -> int:
    """Resolve the listener port: an explicit ``--port`` overrides the profile default."""
    if explicit_port is not None:
        return explicit_port
    return _PROFILE_DEFAULT_PORTS[profile]


def run_serve(
    *,
    profile: ServeProfile,
    host: str,
    certfile: Path,
    keyfile: Path | None,
    port: int | None = None,
    serve_fn: ServeFn | None = None,
) -> int:
    """Run the Core backend listener for ``profile`` (the SINGLE serve impl).

    Both ``serve --ui-bff`` / ``serve --project-api`` and the deprecated
    ``serve-control-plane`` alias funnel through here, so there is exactly one
    transport path. The profile only selects the default port; an explicit
    ``--port`` overrides it.

    Args:
        profile: The backend serve profile (UI-BFF or Project-API).
        host: The bind host.
        certfile: The TLS certificate path (the listener is HTTPS, fail-closed).
        keyfile: The optional TLS key path.
        port: An explicit port override; defaults to the profile port.
        serve_fn: Injection seam for the control-plane entrypoint (tests assert
            delegation without binding a socket); defaults to the productive
            ``serve_control_plane``.

    Returns:
        Process exit code (0 on a clean shutdown).
    """
    resolved_serve = serve_fn if serve_fn is not None else _default_serve_fn()
    resolved_serve(
        host=host,
        port=resolve_serve_port(profile, port),
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
        port: An explicit port override; defaults to :data:`UI_PORT`.
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
    resolved_port = port if port is not None else UI_PORT
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
    if _is_loopback_host(host):
        return
    msg = (
        "agentkit ui serves cleartext HTTP and is restricted to loopback; "
        f"refusing to bind non-loopback host {host!r} "
        "(FK-15 localhost-only). Use 127.0.0.1/localhost, or run the SPA "
        "behind an HTTPS reverse proxy."
    )
    raise UiBindHostError(msg)


def _is_loopback_host(host: str) -> bool:
    candidate = host.strip()
    if not candidate:
        return False
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(candidate, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            return False
        raw_address = str(sockaddr[0])
        try:
            addresses.add(ipaddress.ip_address(raw_address))
        except ValueError:
            return False
    return bool(addresses) and all(address.is_loopback for address in addresses)


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
    "PROJECT_API_PORT",
    "UI_BFF_PORT",
    "UI_PORT",
    "ServeFn",
    "ServeProfile",
    "UiBindHostError",
    "UiServeFn",
    "default_ui_dist_dir",
    "resolve_serve_port",
    "run_serve",
    "run_ui",
]
