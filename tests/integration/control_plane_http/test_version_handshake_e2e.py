"""End-to-end version-handshake over the REAL routing/transport (AG3-121 AC6).

Drives the real ``ControlPlaneApplication`` dispatch (with the handshake
middleware ON) through the real ``BaseHTTPRequestHandler`` on a plain-HTTP
localhost socket, reached by the real ``HttpsJsonTransport`` (urllib). No mock of
the middleware, the router or the transport (testing-guardrails §2):

  - a too-old runtime traverses the real ``/v1`` dispatch and is rejected with
    HTTP 426 ``upgrade_required``;
  - a compatible runtime hits the SAME mutating path and mutates for real.
"""

from __future__ import annotations

import http.client
import json
import threading
from http import HTTPStatus
from http.server import HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.models import TelemetryEventAccepted
from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    _build_handler,
    serve_control_plane,
)
from agentkit.backend.control_plane_http.version_handshake import (
    CLIENT_VERSION_HEADER,
    SKILL_BUNDLE_HEADER,
    CompatWindow,
    VersionAxisWindow,
    VersionHandshakeMiddleware,
)
from agentkit.backend.exceptions import ControlPlaneApiError
from agentkit.harness_client.projectedge.client import HttpsJsonTransport

if TYPE_CHECKING:
    from collections.abc import Iterator

_TELEMETRY_PATH = "/v1/telemetry/events"


class _RecordingTelemetryService:
    """Telemetry spy: records ingest calls, returns an accepted result."""

    def __init__(self) -> None:
        self.calls = 0

    def ingest_event(self, request: object) -> TelemetryEventAccepted:  # noqa: ARG002
        self.calls += 1
        return TelemetryEventAccepted(event_id="evt-e2e")


def _telemetry_payload() -> dict[str, object]:
    return {
        "project_key": "p",
        "story_id": "s",
        "run_id": "r",
        "event_type": "agent_start",
        "occurred_at": "2026-06-29T10:00:00+00:00",
        "source_component": "c",
    }


def _serve(app: ControlPlaneApplication) -> tuple[HTTPServer, threading.Thread]:
    server = HTTPServer(("127.0.0.1", 0), _build_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture()
def too_old_core() -> Iterator[tuple[str, _RecordingTelemetryService]]:
    """A core whose ``min`` is above the installed client version (too-old case)."""
    telemetry = _RecordingTelemetryService()
    window = CompatWindow(
        agent_runtime=VersionAxisWindow(
            min="999.0.0", max="999.0.0", recommended="999.0.0", blocked=(),
        ),
        wire=VersionAxisWindow(min="1", max="1", recommended="1", blocked=()),
    )
    app = ControlPlaneApplication(
        version_handshake_middleware=VersionHandshakeMiddleware(window=window),
        telemetry_service=telemetry,  # type: ignore[arg-type]
    )
    server, thread = _serve(app)
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", telemetry
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture()
def compatible_core() -> Iterator[tuple[str, _RecordingTelemetryService]]:
    """A core whose default window admits the installed client version."""
    telemetry = _RecordingTelemetryService()
    app = ControlPlaneApplication(
        version_handshake_middleware=VersionHandshakeMiddleware(),
        telemetry_service=telemetry,  # type: ignore[arg-type]
    )
    server, thread = _serve(app)
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", telemetry
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_too_old_runtime_is_rejected_426_over_real_wire(
    too_old_core: tuple[str, _RecordingTelemetryService],
) -> None:
    """AC6: a too-old runtime is blocked 426 through the real dispatch."""
    base_url, telemetry = too_old_core
    # The transport sends a bound bundle version so ONLY the runtime axis fails.
    transport = HttpsJsonTransport(base_url=base_url, skill_bundle_version="bundle-1")

    with pytest.raises(ControlPlaneApiError) as exc_info:
        transport.send(
            method="POST", path=_TELEMETRY_PATH, payload=_telemetry_payload(),
        )

    assert exc_info.value.http_status == HTTPStatus.UPGRADE_REQUIRED
    assert exc_info.value.error_code == "upgrade_required"
    assert telemetry.calls == 0


def test_compatible_runtime_mutates_over_real_wire(
    compatible_core: tuple[str, _RecordingTelemetryService],
) -> None:
    """AC6: a compatible request hits the same path and mutates for real."""
    base_url, telemetry = compatible_core
    transport = HttpsJsonTransport(base_url=base_url, skill_bundle_version="bundle-1")

    data = transport.send(
        method="POST", path=_TELEMETRY_PATH, payload=_telemetry_payload(),
    )

    assert data["status"] == "accepted"
    assert telemetry.calls == 1


def test_compat_window_readable_over_real_wire(
    compatible_core: tuple[str, _RecordingTelemetryService],
) -> None:
    """AC1/AC6: GET /v1/compat is readable over the real wire without handshake."""
    base_url, _ = compatible_core
    transport = HttpsJsonTransport(base_url=base_url)

    data = transport.send(method="GET", path="/v1/compat")

    # ``send`` also surfaces the server's correlation id from the response header.
    assert {"agent_runtime", "wire"} <= set(data)
    runtime = data["agent_runtime"]
    assert isinstance(runtime, dict)
    assert set(runtime) == {"min", "max", "recommended", "blocked"}
    wire = data["wire"]
    assert isinstance(wire, dict)
    assert wire["min"] == "1"


# ---------------------------------------------------------------------------
# Item 8 — raw-socket boundary tests (precise header control over the wire)
# ---------------------------------------------------------------------------


def _raw_post(
    base_url: str, path: str, headers: dict[str, str], body: dict[str, object],
) -> tuple[int, dict[str, object]]:
    """POST over a raw HTTP socket with EXACT headers (no transport header magic)."""
    host_port = base_url.removeprefix("http://")
    host, port = host_port.split(":")
    conn = http.client.HTTPConnection(host, int(port))
    try:
        payload = json.dumps(body).encode("utf-8")
        send_headers = {"Content-Type": "application/json", **headers}
        conn.request("POST", path, body=payload, headers=send_headers)
        response = conn.getresponse()
        raw = response.read()
        return response.status, json.loads(raw) if raw else {}
    finally:
        conn.close()


@pytest.fixture()
def gated_core() -> Iterator[tuple[str, _RecordingTelemetryService]]:
    """A gated core with a [1.0.0, 3.0.0] runtime window and a telemetry spy."""
    telemetry = _RecordingTelemetryService()
    window = CompatWindow(
        agent_runtime=VersionAxisWindow(
            min="1.0.0", max="3.0.0", recommended="2.0.0", blocked=(),
        ),
        wire=VersionAxisWindow(min="1", max="1", recommended="1", blocked=()),
    )
    app = ControlPlaneApplication(
        version_handshake_middleware=VersionHandshakeMiddleware(window=window),
        telemetry_service=telemetry,  # type: ignore[arg-type]
    )
    server, thread = _serve(app)
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", telemetry
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_missing_handshake_header_426_over_socket(
    gated_core: tuple[str, _RecordingTelemetryService],
) -> None:
    """Item 8: a handshake-less mutation is rejected 426 at the real socket boundary."""
    base_url, telemetry = gated_core

    status, payload = _raw_post(base_url, _TELEMETRY_PATH, {}, _telemetry_payload())

    assert status == int(HTTPStatus.UPGRADE_REQUIRED)
    assert payload["error_code"] == "upgrade_required"
    assert telemetry.calls == 0


def test_unsupported_wire_426_over_socket(
    gated_core: tuple[str, _RecordingTelemetryService],
) -> None:
    """Item 8: an unsupported wire version is rejected 426 at the socket boundary."""
    base_url, telemetry = gated_core

    status, _ = _raw_post(
        base_url,
        "/v2/telemetry/events",
        {CLIENT_VERSION_HEADER: "2.0.0", SKILL_BUNDLE_HEADER: "b"},
        _telemetry_payload(),
    )

    assert status == int(HTTPStatus.UPGRADE_REQUIRED)
    assert telemetry.calls == 0


def test_above_max_runtime_426_over_socket(
    gated_core: tuple[str, _RecordingTelemetryService],
) -> None:
    """Item 8: an above-max runtime is rejected 426 at the socket boundary."""
    base_url, telemetry = gated_core

    status, _ = _raw_post(
        base_url,
        _TELEMETRY_PATH,
        {CLIENT_VERSION_HEADER: "9.9.9", SKILL_BUNDLE_HEADER: "b"},
        _telemetry_payload(),
    )

    assert status == int(HTTPStatus.UPGRADE_REQUIRED)
    assert telemetry.calls == 0


# ---------------------------------------------------------------------------
# Item 5 / Item 8 — production wiring (serve_control_plane) is never fail-open
# ---------------------------------------------------------------------------


class _FakeHttpsServer:
    """Capture the handler class without binding a TLS socket."""

    last_handler_cls: object = None

    def __init__(
        self,
        address: tuple[str, int],
        handler_cls: object,
        *,
        certfile: str,
        keyfile: str | None,
    ) -> None:
        del address, certfile, keyfile
        _FakeHttpsServer.last_handler_cls = handler_cls

    def serve_forever(self) -> None:
        """No-op (the test never blocks on a real listener)."""

    def server_close(self) -> None:
        """No-op."""


def test_serve_control_plane_app_none_is_handshake_gated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item 5/8: the app=None production wiring is always handshake-gated (no fail-open)."""
    captured: dict[str, ControlPlaneApplication] = {}
    real_build_handler = _build_handler

    def _spy_build_handler(app: ControlPlaneApplication) -> object:
        captured["app"] = app
        return real_build_handler(app)

    monkeypatch.setattr(
        "agentkit.backend.control_plane_http.app.ThreadingHTTPSServer",
        _FakeHttpsServer,
    )
    monkeypatch.setattr(
        "agentkit.backend.control_plane_http.app._build_handler", _spy_build_handler,
    )

    # AG3-138: this E2E test verifies handshake gating, not the pre-serve startup
    # hook (instance-identity + reconciliation, which needs a Postgres backend and
    # has its own dedicated tests). Inject a no-op hook so the handshake-gating
    # wiring is exercised without a live control-plane backend.
    serve_control_plane(
        certfile=Path("tls/control-plane.pem"),
        app=None,
        startup_hook=lambda _app: None,
    )

    # The production builder must never serve an ungated app (FK-91 Regel 11).
    assert captured["app"]._version_handshake is not None


def test_serve_control_plane_gates_injected_ungated_app_over_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item 5/8: an injected ungated app is gated by serve_control_plane and 426s.

    Proves the fail-OPEN path is closed: even when a caller injects an app built
    WITHOUT a handshake middleware, ``serve_control_plane`` guarantees the real
    listener rejects a handshake-less mutation BEFORE any side effect.
    """
    telemetry = _RecordingTelemetryService()
    ungated = ControlPlaneApplication(telemetry_service=telemetry)  # type: ignore[arg-type]
    assert ungated._version_handshake is None  # precondition: would be fail-open

    monkeypatch.setattr(
        "agentkit.backend.control_plane_http.app.ThreadingHTTPSServer",
        _FakeHttpsServer,
    )
    # AG3-138: no-op startup hook (handshake-gating concern only; see above).
    serve_control_plane(
        certfile=Path("tls/control-plane.pem"),
        app=ungated,
        startup_hook=lambda _app: None,
    )

    # serve_control_plane must have injected the fail-closed handshake middleware.
    assert ungated._version_handshake is not None

    handler_cls = _FakeHttpsServer.last_handler_cls
    server = HTTPServer(("127.0.0.1", 0), handler_cls)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        status, payload = _raw_post(
            f"http://{host}:{port}", _TELEMETRY_PATH, {}, _telemetry_payload(),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == int(HTTPStatus.UPGRADE_REQUIRED)
    assert payload["error_code"] == "upgrade_required"
    assert telemetry.calls == 0


def test_auth_login_without_handshake_works_through_production_wiring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item 1/8: POST /v1/auth/login without X-AK3-* is NOT 426 through production wiring."""
    monkeypatch.setattr(
        "agentkit.backend.control_plane_http.app.ThreadingHTTPSServer",
        _FakeHttpsServer,
    )
    # AG3-138: no-op startup hook (handshake-gating concern only; see above).
    serve_control_plane(
        certfile=Path("tls/control-plane.pem"),
        app=None,
        startup_hook=lambda _app: None,
    )

    handler_cls = _FakeHttpsServer.last_handler_cls
    server = HTTPServer(("127.0.0.1", 0), handler_cls)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        status, _ = _raw_post(
            f"http://{host}:{port}",
            "/v1/auth/login",
            {},
            {"username": "x", "password": "y", "project_key": "p"},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # Login is handshake-exempt: it must reach the auth handler, never 426.
    assert status != int(HTTPStatus.UPGRADE_REQUIRED)
