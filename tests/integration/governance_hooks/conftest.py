"""Shared fixtures for hook<->core REST mediation integration tests (AG3-129).

The hook path is exercised over a REAL plain-HTTP control-plane server bound to a
REAL ephemeral Postgres test schema (the server-side state backend). No route is
mocked; the hook's REST client rides the wire exactly as in production.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import HTTPServer
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    _build_handler,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture()
def control_plane_base_url(postgres_isolated_schema: str) -> Iterator[str]:
    """Boot the real control-plane handler on a plain-HTTP localhost socket.

    Depends on ``postgres_isolated_schema`` so the server-side services persist
    to a real, per-test Postgres schema (no direct-DB shortcut on the hook side).
    """
    _ = postgres_isolated_schema  # env (backend/url/schema) is set by the fixture
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


@pytest.fixture()
def unreachable_base_url(postgres_isolated_schema: str) -> str:
    """Return a localhost base URL whose port has no listener (connection refused).

    Depends on ``postgres_isolated_schema`` so the read-back assertions still run
    against a real backend while the hook's REST calls fail (core unreachable).
    """
    _ = postgres_isolated_schema
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    return f"http://127.0.0.1:{port}"


def write_control_plane_config(project_root: Path, base_url: str) -> None:
    """Write the local ``control-plane.json`` the hook REST client reads."""
    config_dir = project_root / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "control-plane.json").write_text(
        json.dumps({"base_url": base_url}), encoding="utf-8"
    )
