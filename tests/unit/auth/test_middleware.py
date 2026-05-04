from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.auth.middleware import AuthMiddleware, AuthMiddlewareResponse
from agentkit.auth.sessions import InMemorySessionStore
from agentkit.auth.tokens import issue_project_api_token

if TYPE_CHECKING:
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
        token = self.tokens[token_id]
        assert token.project_key == project_key
        self.tokens[token_id] = token.model_copy(update={"revoked_at": token.created_at})


def test_middleware_rejects_missing_credentials() -> None:
    middleware = AuthMiddleware(token_repository=_InMemoryTokenRepository())

    result = middleware.authorize(
        method="GET",
        route_path="/v1/projects/tenant-a/stories",
        request_headers={},
        correlation_id="req-auth",
    )

    assert isinstance(result, AuthMiddlewareResponse)
    assert result.status_code == HTTPStatus.UNAUTHORIZED


def test_middleware_accepts_cookie_session_with_csrf_for_mutation() -> None:
    sessions = InMemorySessionStore()
    session = sessions.create()
    middleware = AuthMiddleware(
        session_store=sessions,
        token_repository=_InMemoryTokenRepository(),
    )

    result = middleware.authorize(
        method="POST",
        route_path="/v1/projects/tenant-a/stories",
        request_headers={
            "Cookie": f"ak3_session={session.session_id}",
            "X-CSRF-Token": session.csrf_token,
        },
        correlation_id="req-auth",
    )

    assert not isinstance(result, AuthMiddlewareResponse)
    assert result.auth_kind == "strategist_session"


def test_middleware_rejects_project_api_token_mismatch() -> None:
    repository = _InMemoryTokenRepository()
    issued = issue_project_api_token(
        project_key="tenant-a",
        label="thin-client",
        repository=repository,
    )
    middleware = AuthMiddleware(token_repository=repository)

    result = middleware.authorize(
        method="GET",
        route_path="/v1/projects/tenant-b/stories",
        request_headers={"Authorization": f"Bearer {issued.plaintext_token}"},
        correlation_id="req-auth",
    )

    assert isinstance(result, AuthMiddlewareResponse)
    assert result.status_code == HTTPStatus.FORBIDDEN
