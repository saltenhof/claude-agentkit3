from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.auth.middleware import AuthMiddleware, AuthMiddlewareResponse
from agentkit.backend.auth.sessions import InMemorySessionStore
from agentkit.harness_client.projectedge.credentials import prepare_project_api_token

if TYPE_CHECKING:
    from agentkit.backend.auth.entities import ProjectApiToken


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

    def insert(self, token: ProjectApiToken) -> None:
        if token.token_id in self.tokens:
            raise ValueError("duplicate token id")
        self.tokens[token.token_id] = token

    def mark_used(self, token_id: str, *, used_at: object) -> None:
        self.tokens[token_id] = self.tokens[token_id].model_copy(
            update={"last_used_at": used_at},
        )

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
    issued = prepare_project_api_token(
        project_key="tenant-a",
        label="thin-client",
    )
    repository.insert(issued.record)
    middleware = AuthMiddleware(token_repository=repository)

    result = middleware.authorize(
        method="GET",
        route_path="/v1/projects/tenant-b/stories",
        request_headers={"Authorization": f"Bearer {issued.plaintext_token}"},
        correlation_id="req-auth",
    )

    assert isinstance(result, AuthMiddlewareResponse)
    assert result.status_code == HTTPStatus.FORBIDDEN


def test_first_credential_installer_exception_allows_strategist_before_any_token() -> None:
    sessions = InMemorySessionStore()
    session = sessions.create()
    middleware = AuthMiddleware(
        session_store=sessions,
        token_repository=_InMemoryTokenRepository(),
    )

    result = middleware.authorize(
        method="POST",
        route_path="/v1/projects/tenant-a/installation/third-party-validation",
        request_headers={
            "Cookie": f"ak3_session={session.session_id}",
            "X-CSRF-Token": session.csrf_token,
        },
        correlation_id="req-first-credential",
    )

    assert not isinstance(result, AuthMiddlewareResponse)
    assert result.auth_kind == "strategist_session"


def test_first_credential_installer_exception_rejects_strategist_after_token_exists() -> None:
    sessions = InMemorySessionStore()
    session = sessions.create()
    repository = _InMemoryTokenRepository()
    repository.insert(
        prepare_project_api_token(project_key="tenant-a", label="thin-client").record,
    )
    middleware = AuthMiddleware(session_store=sessions, token_repository=repository)

    result = middleware.authorize(
        method="POST",
        route_path="/v1/projects/tenant-a/installation/third-party-validation",
        request_headers={
            "Cookie": f"ak3_session={session.session_id}",
            "X-CSRF-Token": session.csrf_token,
        },
        correlation_id="req-after-credential",
    )

    assert isinstance(result, AuthMiddlewareResponse)
    assert result.status_code == HTTPStatus.FORBIDDEN
