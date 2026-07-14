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

from agentkit.backend.auth.middleware import AuthMiddleware
from agentkit.backend.auth.tokens import issue_project_api_token
from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    _build_handler,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from agentkit.backend.auth.entities import ProjectApiToken


class _TokenRepository:
    """In-memory authentication repository for the real HTTP fixture."""

    def __init__(self) -> None:
        self.rows: dict[str, ProjectApiToken] = {}

    def get(self, token_id: str) -> ProjectApiToken | None:
        return self.rows.get(token_id)

    def get_by_hash(self, token_hash: str) -> ProjectApiToken | None:
        return next((row for row in self.rows.values() if row.token_hash == token_hash), None)

    def list_for_project(self, project_key: str) -> list[ProjectApiToken]:
        return [row for row in self.rows.values() if row.project_key == project_key]

    def save(self, token: ProjectApiToken) -> None:
        self.rows[token.token_id] = token

    def revoke(self, project_key: str, token_id: str) -> None:
        del project_key, token_id


@pytest.fixture()
def control_plane_base_url(
    postgres_isolated_schema: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """Boot the real control-plane handler on a plain-HTTP localhost socket.

    Depends on ``postgres_isolated_schema`` so the server-side services persist
    to a real, per-test Postgres schema (no direct-DB shortcut on the hook side).
    """
    _ = postgres_isolated_schema  # env (backend/url/schema) is set by the fixture
    auth = AuthMiddleware(token_repository=_TokenRepository())
    issued = issue_project_api_token(
        project_key="tenant-a", label="integration-hook", repository=auth.token_repository
    )
    monkeypatch.setenv("AGENTKIT_PROJECT_API_TOKEN", issued.plaintext_token)
    app = ControlPlaneApplication(auth_middleware=auth)
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
    project_config = config_dir / "project.yaml"
    if not project_config.exists():
        project_config.write_text(
            "project_key: tenant-a\n"
            "project_name: Tenant A\n"
            "repositories:\n  - name: app\n    path: .\n"
            "pipeline:\n"
            "  config_version: '3.0'\n"
            "  features:\n    multi_llm: false\n"
            "  sonarqube:\n    available: false\n    enabled: false\n"
            "  ci:\n    available: false\n    enabled: false\n",
            encoding="utf-8",
        )
