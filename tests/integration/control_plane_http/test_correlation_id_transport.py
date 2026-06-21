"""Production-transport correlation-id round-trip (AG3-114 R2, Codex finding #2).

The official :class:`~agentkit.harness_client.projectedge.client.HttpsJsonTransport` sends the
stable correlation id as the ``X-Correlation-Id`` request header (FK-91 §91.1a
Regel #7). ``urllib.request.Request`` capitalizes header names on the wire
(``X-Correlation-Id`` -> ``X-correlation-id``); HTTP header names are
case-insensitive (RFC 9110 §5.1), so the control plane MUST adopt the client's id
regardless of the transmitted casing instead of minting a divergent ``req-<uuid>``.

This drives the REAL transport stack end-to-end over a real socket: the real
``BaseHTTPRequestHandler`` from :func:`_build_handler` (the same handler the HTTPS
server uses) on a plain-HTTP ``HTTPServer``, reached by the real
``HttpsJsonTransport`` (urllib) over ``http://``. It asserts the SAME id is echoed
on BOTH a success (200) and an error (404) response — no stub of the transport,
the server router or the header handling.
"""

from __future__ import annotations

import threading
from http import HTTPStatus
from http.server import HTTPServer
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    _build_handler,
)
from agentkit.harness_client.projectedge.client import HttpsJsonTransport

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture()
def control_plane_base_url() -> Iterator[str]:
    """Boot the REAL control-plane handler on a plain-HTTP localhost socket."""
    app = ControlPlaneApplication()
    server = HTTPServer(("127.0.0.1", 0), _build_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_correlation_id_adopted_over_real_transport_on_success(
    control_plane_base_url: str,
) -> None:
    """Regel #7: the server adopts the client's id on a 200 over the real wire."""
    transport = HttpsJsonTransport(base_url=control_plane_base_url)

    data = transport.send(
        method="GET",
        path="/healthz",
        headers={"X-Correlation-Id": "corr-success-1"},
    )

    # ``send`` surfaces the server's echoed id when the body omits it; the id the
    # server audited is the client's, not a divergent ``req-<uuid>``.
    assert data.get("correlation_id") == "corr-success-1"


def test_correlation_id_adopted_over_real_transport_on_error(
    control_plane_base_url: str,
) -> None:
    """Regel #7: the SAME id is echoed on an error (404) over the real wire.

    A 404 conforms to the stable error contract (``error_code`` / ``error`` /
    ``correlation_id``), so the transport raises ``ControlPlaneApiError`` carrying
    the adopted id — which must equal the client's, proving the case-insensitive
    server lookup on the error path too.
    """
    from agentkit.backend.exceptions import ControlPlaneApiError

    transport = HttpsJsonTransport(base_url=control_plane_base_url)

    with pytest.raises(ControlPlaneApiError) as exc_info:
        transport.send(
            method="GET",
            path="/v1/projects/myproj/unknown-endpoint-xyz",
            headers={"X-Correlation-Id": "corr-error-1"},
        )

    assert exc_info.value.http_status == HTTPStatus.NOT_FOUND
    assert exc_info.value.correlation_id == "corr-error-1"
