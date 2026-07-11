"""Authentication middleware for control-plane HTTP requests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.auth.errors import AuthFailedError, ProjectMismatchError
from agentkit.backend.auth.sessions import InMemorySessionStore
from agentkit.backend.auth.tokens import validate_project_api_token

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from agentkit.backend.auth.repository import ProjectApiTokenRepository

_CORRELATION_HEADER = "X-Correlation-Id"
_SESSION_COOKIE = "ak3_session"
_CSRF_HEADER = "X-CSRF-Token"
_PROJECT_PATH = re.compile(r"^/v1/projects/(?P<project_key>[^/]+)(?:/.*)?$")
_UNAUTHENTICATED_PATHS = {"/healthz", "/v1/auth/login"}
_PROJECT_TOKEN_MANAGEMENT = re.compile(
    r"^/v1/projects/[^/]+/api-tokens(?:/[^/]+)?$",
)
_OWNERSHIP_TRANSFER_PATH = re.compile(
    r"^/v1/project-edge/story-runs/[^/]+/ownership/"
    r"takeover-(?:request|confirm|deny|reconcile-clear|reconcile-worktree)$",
)
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class AuthResult:
    """Authenticated request context."""

    auth_kind: str
    project_key: str | None = None
    session_id: str | None = None
    token_id: str | None = None

    @property
    def is_human_bff_session(self) -> bool:
        """Whether this result came from a human BFF session."""
        return self.auth_kind == "strategist_session"


@dataclass(frozen=True)
class AuthMiddlewareResponse:
    """Serializable error response produced by auth middleware."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


class AuthMiddleware:
    """Fail-closed authentication gate for control-plane routes."""

    def __init__(
        self,
        *,
        session_store: InMemorySessionStore | None = None,
        token_repository: ProjectApiTokenRepository | None = None,
    ) -> None:
        if token_repository is None:
            from agentkit.backend.state_backend.store.auth_repository import (
                StateBackendProjectApiTokenRepository,
            )

            token_repository = StateBackendProjectApiTokenRepository()
        self._session_store = session_store or InMemorySessionStore()
        self._token_repository = token_repository

    @property
    def session_store(self) -> InMemorySessionStore:
        """Return the session store used by this middleware."""

        return self._session_store

    @property
    def token_repository(self) -> ProjectApiTokenRepository:
        """Return the token repository used by this middleware."""

        return self._token_repository

    def authorize(
        self,
        *,
        method: str,
        route_path: str,
        request_headers: Mapping[str, str] | None,
        correlation_id: str,
    ) -> AuthResult | AuthMiddlewareResponse:
        """Authorize a request or return an HTTP error response."""

        if route_path in _UNAUTHENTICATED_PATHS:
            return AuthResult(auth_kind="none")

        headers = _normalized_headers(request_headers)
        project_key = _project_key_from_path(route_path) or headers.get("x-project-key")
        bearer = _bearer_token(headers)
        if bearer is not None:
            if project_key is None:
                return _unauthorized_response(correlation_id)
            try:
                token = validate_project_api_token(
                    plaintext_token=bearer,
                    project_key=project_key,
                    repository=self._token_repository,
                )
            except ProjectMismatchError:
                return _forbidden_response(correlation_id)
            except AuthFailedError:
                return _unauthorized_response(correlation_id)
            return AuthResult(
                auth_kind="project_api_token",
                project_key=project_key,
                token_id=token.token_id,
            )

        session_id = _session_cookie(headers)
        if session_id is None:
            return _unauthorized_response(correlation_id)
        try:
            session = self._session_store.validate(session_id)
        except AuthFailedError:
            return _unauthorized_response(correlation_id)
        if method.upper() in _MUTATING_METHODS and not _csrf_matches(headers, session.csrf_token):
            return _forbidden_response(correlation_id)
        return AuthResult(
            auth_kind="strategist_session",
            project_key=project_key,
            session_id=session.session_id,
        )

    @staticmethod
    def session_cookie_name() -> str:
        """Return the strategist session cookie name."""

        return _SESSION_COOKIE

    @staticmethod
    def csrf_header_name() -> str:
        """Return the CSRF header name."""

        return _CSRF_HEADER


def is_project_api_token_management_path(route_path: str) -> bool:
    """Return whether a route path manages project API tokens."""

    return _PROJECT_TOKEN_MANAGEMENT.match(route_path) is not None


def is_ownership_transfer_path(route_path: str) -> bool:
    """Return whether a route path is an ownership-transfer endpoint."""

    return _OWNERSHIP_TRANSFER_PATH.match(route_path) is not None


def _project_key_from_path(route_path: str) -> str | None:
    match = _PROJECT_PATH.match(route_path)
    if match is None:
        return None
    return match.group("project_key")


def _normalized_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    if headers is None:
        return {}
    return {key.lower(): value for key, value in headers.items()}


def _bearer_token(headers: Mapping[str, str]) -> str | None:
    authorization = headers.get("authorization")
    if authorization is None:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    token = authorization[len(prefix) :].strip()
    return token or None


def _session_cookie(headers: Mapping[str, str]) -> str | None:
    raw_cookie = headers.get("cookie")
    if raw_cookie is None:
        return None
    for item in raw_cookie.split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name == _SESSION_COOKIE and value:
            return value
    return None


def _csrf_matches(headers: Mapping[str, str], expected: str) -> bool:
    provided = headers.get(_CSRF_HEADER.lower())
    return provided == expected


def _json_response(
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    correlation_id: str,
    headers: Sequence[tuple[str, str]] = (),
) -> AuthMiddlewareResponse:
    return AuthMiddlewareResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),) + tuple(headers),
    )


def _unauthorized_response(correlation_id: str) -> AuthMiddlewareResponse:
    return _json_response(
        HTTPStatus.UNAUTHORIZED,
        {
            "error_code": "unauthorized",
            "error": "Unauthorized",
            "correlation_id": correlation_id,
        },
        correlation_id=correlation_id,
    )


def _forbidden_response(correlation_id: str) -> AuthMiddlewareResponse:
    return _json_response(
        HTTPStatus.FORBIDDEN,
        {
            "error_code": "forbidden",
            "error": "Forbidden",
            "correlation_id": correlation_id,
        },
        correlation_id=correlation_id,
    )
