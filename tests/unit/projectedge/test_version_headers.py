"""Project-edge client version-handshake headers (AG3-121 AC5, FK-91 Regel 11).

The REAL ``HttpsJsonTransport.send`` runs against a request-capture HTTP server
(a transport spy over a real socket) so the test asserts the headers actually
put on the wire — not a hand-assembled header dict. It proves ``X-AK3-Client``
(installed package metadata version), ``X-AK3-Skill-Bundle`` (bound bundle
version), an unchanged ``Content-Type`` and an intact correlation pass-through
(FK-91 §91.1a Regel #7).
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.metadata import version
from typing import TYPE_CHECKING

import pytest

from agentkit.harness_client.projectedge.client import HttpsJsonTransport
from agentkit.harness_client.projectedge.runtime import (
    _read_bound_skill_bundle_version,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_CAPTURED: list[dict[str, str]] = []


class _CaptureHandler(BaseHTTPRequestHandler):
    """Capture request headers and answer with a minimal JSON object."""

    def do_GET(self) -> None:  # noqa: N802
        _CAPTURED.append({key: value for key, value in self.headers.items()})
        body = b'{"correlation_id": "server-id"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, message_format: str, *args: object) -> None:
        del message_format, args


@pytest.fixture()
def capture_server() -> Iterator[str]:
    _CAPTURED.clear()
    server = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _lookup_ci(headers: dict[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def test_real_transport_sends_version_headers(capture_server: str) -> None:
    """AC5: the real send puts X-AK3-Client + X-AK3-Skill-Bundle on the wire."""
    transport = HttpsJsonTransport(
        base_url=capture_server, skill_bundle_version="bundle-9.9.9",
    )

    transport.send(
        method="GET",
        path="/capture",
        headers={"X-Correlation-Id": "corr-123"},
    )

    assert len(_CAPTURED) == 1
    captured = _CAPTURED[0]
    assert _lookup_ci(captured, "X-AK3-Client") == version("agentkit")
    assert _lookup_ci(captured, "X-AK3-Skill-Bundle") == "bundle-9.9.9"
    # Content-Type unchanged and correlation pass-through intact (Regel #7).
    assert _lookup_ci(captured, "Content-Type") == "application/json"
    assert _lookup_ci(captured, "X-Correlation-Id") == "corr-123"


def test_real_transport_ignores_caller_handshake_header_overrides(
    capture_server: str,
) -> None:
    """AC5 (adversarial): a caller cannot forge the handshake headers via ``headers=``.

    The computed ``X-AK3-Client``/``X-AK3-Skill-Bundle``/``Content-Type`` are
    authoritative (FK-91 §91.1a Regel 11): a caller passing spoofed values in
    ``headers=`` must NOT reach the wire — otherwise a too-old/blocked client could
    masquerade as compatible. Only the correlation pass-through (Regel #7) is
    caller-controlled. Asserted against the headers actually put on the wire.
    """
    transport = HttpsJsonTransport(
        base_url=capture_server, skill_bundle_version="bundle-9.9.9",
    )

    transport.send(
        method="GET",
        path="/capture",
        headers={
            "X-AK3-Client": "9.9.9",
            "X-AK3-Skill-Bundle": "fake",
            "Content-Type": "text/evil",
            "X-Correlation-Id": "ok",
        },
    )

    captured = _CAPTURED[0]
    # The spoofed handshake/content headers are dropped in favour of the computed
    # authoritative values (caller values ignored).
    assert _lookup_ci(captured, "X-AK3-Client") == version("agentkit")
    assert _lookup_ci(captured, "X-AK3-Skill-Bundle") == "bundle-9.9.9"
    assert _lookup_ci(captured, "Content-Type") == "application/json"
    # Only the correlation header is caller-controlled (Regel #7).
    assert _lookup_ci(captured, "X-Correlation-Id") == "ok"


def test_real_transport_omits_skill_bundle_when_unbound(capture_server: str) -> None:
    """No bound bundle -> no X-AK3-Skill-Bundle (core then fails closed)."""
    transport = HttpsJsonTransport(base_url=capture_server)

    transport.send(method="GET", path="/capture")

    captured = _CAPTURED[0]
    assert _lookup_ci(captured, "X-AK3-Client") == version("agentkit")
    assert _lookup_ci(captured, "X-AK3-Skill-Bundle") is None


# ---------------------------------------------------------------------------
# Bound bundle version source (the prompt-bundle lock is the SSOT)
# ---------------------------------------------------------------------------


def _write_lock(project_root: Path, content: str) -> None:
    lock_path = project_root / ".agentkit" / "config" / "prompt-bundle.lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(content, encoding="utf-8")


def test_read_bound_skill_bundle_version_from_lock(tmp_path: Path) -> None:
    """The bound bundle version is read from the prompt-bundle lock."""
    _write_lock(tmp_path, '{"bundle_id": "core", "bundle_version": "2.3.4"}')

    assert _read_bound_skill_bundle_version(tmp_path) == "2.3.4"


def test_read_bound_skill_bundle_version_missing_lock(tmp_path: Path) -> None:
    """No lock -> None (the client never invents a bundle version)."""
    assert _read_bound_skill_bundle_version(tmp_path) is None


def test_read_bound_skill_bundle_version_malformed_lock(tmp_path: Path) -> None:
    """A malformed / version-less lock -> None (fail-closed, not a guess)."""
    _write_lock(tmp_path, "not-json")
    assert _read_bound_skill_bundle_version(tmp_path) is None

    _write_lock(tmp_path, '{"bundle_id": "core"}')
    assert _read_bound_skill_bundle_version(tmp_path) is None
