from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.auth.credentials import StrategistCredentialStore
from agentkit.auth.http.routes import AuthRoutes
from agentkit.auth.middleware import AuthMiddleware
from agentkit.auth.sessions import InMemorySessionStore
from agentkit.control_plane.http import ControlPlaneApplication, HttpResponse

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.auth.entities import ProjectApiToken


class _InMemoryTokenRepository:
    def __init__(self) -> None:
        self.tokens: dict[str, ProjectApiToken] = {}

    def get(self, token_id: str) -> ProjectApiToken | None:
        return self.tokens.get(token_id)

    def get_by_hash(self, token_hash: str) -> ProjectApiToken | None:
        for token in self.tokens.values():
            if token.token_hash == token_hash:
                return token
        return None

    def list_for_project(self, project_key: str) -> list[ProjectApiToken]:
        return [token for token in self.tokens.values() if token.project_key == project_key]

    def save(self, token: ProjectApiToken) -> None:
        self.tokens[token.token_id] = token

    def revoke(self, project_key: str, token_id: str) -> None:
        token = self.tokens.get(token_id)
        if token is None or token.project_key != project_key:
            from agentkit.auth.errors import TokenNotFoundError

            raise TokenNotFoundError("Project API token not found")
        self.tokens[token_id] = token.model_copy(update={"revoked_at": token.created_at})


def _json_body(response: HttpResponse) -> dict[str, object]:
    body = json.loads(response.body)
    assert isinstance(body, dict)
    return body


def _header(response: HttpResponse, name: str) -> str:
    for key, value in response.headers:
        if key == name:
            return value
    raise AssertionError(f"Missing header {name}")


def _app(tmp_path: Path) -> tuple[ControlPlaneApplication, _InMemoryTokenRepository]:
    credentials = StrategistCredentialStore(tmp_path / "auth.json")
    credentials.set_password("secret", username="strategist")
    sessions = InMemorySessionStore()
    tokens = _InMemoryTokenRepository()
    routes = AuthRoutes(
        credential_store=credentials,
        session_store=sessions,
        token_repository=tokens,
    )
    middleware = AuthMiddleware(session_store=sessions, token_repository=tokens)
    return ControlPlaneApplication(
        auth_routes=routes,
        auth_middleware=middleware,
    ), tokens


def test_login_sets_session_cookie_and_returns_csrf(tmp_path: Path) -> None:
    app, _tokens = _app(tmp_path)

    response = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps(
            {"username": "strategist", "password": "secret"},
        ).encode("utf-8"),
        request_headers={"X-Correlation-Id": "req-login"},
    )

    body = _json_body(response)
    assert response.status_code == HTTPStatus.OK
    assert body["status"] == "authenticated"
    assert isinstance(body["csrf_token"], str)
    assert _header(response, "Set-Cookie").startswith("ak3_session=")


def test_project_api_token_lifecycle_routes(tmp_path: Path) -> None:
    app, tokens = _app(tmp_path)
    login = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=json.dumps(
            {"username": "strategist", "password": "secret"},
        ).encode("utf-8"),
    )
    csrf = str(_json_body(login)["csrf_token"])
    cookie = _header(login, "Set-Cookie").split(";", maxsplit=1)[0]
    headers = {"Cookie": cookie, "X-CSRF-Token": csrf}

    created = app.handle_request(
        method="POST",
        path="/v1/projects/tenant-a/api-tokens",
        body=json.dumps(
            {"label": "edge-client", "op_id": "op-token-create"},
        ).encode("utf-8"),
        request_headers=headers,
    )
    listed = app.handle_request(
        method="GET",
        path="/v1/projects/tenant-a/api-tokens",
        body=b"",
        request_headers={"Cookie": cookie},
    )
    token = next(iter(tokens.tokens.values()))
    deleted = app.handle_request(
        method="DELETE",
        path=f"/v1/projects/tenant-a/api-tokens/{token.token_id}",
        body=b"",
        request_headers=headers,
    )

    create_body = _json_body(created)
    assert created.status_code == HTTPStatus.CREATED
    assert create_body["op_id"] == "op-token-create"
    assert "plaintext_token" in create_body
    assert listed.status_code == HTTPStatus.OK
    assert _json_body(listed)["tokens"]
    assert deleted.status_code == HTTPStatus.OK
    assert tokens.tokens[token.token_id].revoked_at is not None
