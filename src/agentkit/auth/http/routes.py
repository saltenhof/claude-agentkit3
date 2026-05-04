"""Authentication routes for the custom control-plane HTTP dispatcher."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentkit.auth.credentials import StrategistCredentialStore
from agentkit.auth.entities import StrategistCredentials
from agentkit.auth.errors import AuthFailedError, TokenNotFoundError
from agentkit.auth.middleware import AuthMiddleware
from agentkit.auth.sessions import InMemorySessionStore
from agentkit.auth.tokens import issue_project_api_token

if TYPE_CHECKING:
    from collections.abc import Mapping

    from agentkit.auth.entities import ProjectApiToken, Session
    from agentkit.auth.repository import ProjectApiTokenRepository

_CORRELATION_HEADER = "X-Correlation-Id"
_TOKEN_COLLECTION_PATH = re.compile(r"^/v1/projects/(?P<project_key>[^/]+)/api-tokens$")
_TOKEN_DETAIL_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/api-tokens/(?P<token_id>[^/]+)$",
)


@dataclass(frozen=True)
class AuthRouteResponse:
    """Serializable response produced by auth routes."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


class LoginRequest(BaseModel):
    """Request body for strategist login."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    username: str
    password: str = Field(min_length=1)


class CreateProjectApiTokenRequest(BaseModel):
    """Request body for issuing a project API token."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = "thin-client"
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")


class RevokeProjectApiTokenRequest(BaseModel):
    """Request body accepted for token revocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")


class AuthRoutes:
    """Route handler for login, logout, and project API token management."""

    def __init__(
        self,
        *,
        credential_store: StrategistCredentialStore | None = None,
        session_store: InMemorySessionStore | None = None,
        token_repository: ProjectApiTokenRepository | None = None,
    ) -> None:
        if token_repository is None:
            from agentkit.state_backend.store.auth_repository import (
                StateBackendProjectApiTokenRepository,
            )

            token_repository = StateBackendProjectApiTokenRepository()
        self._credential_store = credential_store or StrategistCredentialStore()
        self._session_store = session_store or InMemorySessionStore()
        self._token_repository = token_repository

    @property
    def session_store(self) -> InMemorySessionStore:
        """Return the shared session store."""

        return self._session_store

    @property
    def token_repository(self) -> ProjectApiTokenRepository:
        """Return the project API token repository."""

        return self._token_repository

    def handle_get(
        self,
        route_path: str,
        correlation_id: str,
    ) -> AuthRouteResponse | None:
        """Handle auth GET routes or return None."""

        match = _TOKEN_COLLECTION_PATH.match(route_path)
        if match is None:
            return None
        tokens = self._token_repository.list_for_project(match.group("project_key"))
        return _json_response(
            HTTPStatus.OK,
            {"tokens": [_token_payload(token) for token in tokens]},
            correlation_id=correlation_id,
        )

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
        request_headers: Mapping[str, str] | None,
    ) -> AuthRouteResponse | None:
        """Handle auth POST routes or return None."""

        if route_path == "/v1/auth/login":
            return self._handle_login(payload, correlation_id)
        if route_path == "/v1/auth/logout":
            return self._handle_logout(correlation_id, request_headers)
        match = _TOKEN_COLLECTION_PATH.match(route_path)
        if match is None:
            return None
        return self._handle_create_token(match.group("project_key"), payload, correlation_id)

    def handle_delete(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> AuthRouteResponse | None:
        """Handle auth DELETE routes or return None."""

        match = _TOKEN_DETAIL_PATH.match(route_path)
        if match is None:
            return None
        return self._handle_revoke_token(
            match.group("project_key"),
            match.group("token_id"),
            payload,
            correlation_id,
        )

    def _handle_login(
        self,
        payload: object,
        correlation_id: str,
    ) -> AuthRouteResponse:
        try:
            request = LoginRequest.model_validate(payload)
            self._credential_store.verify(
                StrategistCredentials(
                    username=request.username,
                    password=request.password,
                ),
            )
        except (ValidationError, AuthFailedError):
            return _unauthorized_response(correlation_id)
        session = self._session_store.create()
        return _json_response(
            HTTPStatus.OK,
            {
                "status": "authenticated",
                "csrf_token": session.csrf_token,
                "session": _session_payload(session),
            },
            correlation_id=correlation_id,
            headers=(_session_cookie(session),),
        )

    def _handle_logout(
        self,
        correlation_id: str,
        request_headers: Mapping[str, str] | None,
    ) -> AuthRouteResponse:
        session_id = _session_cookie_from_headers(request_headers)
        if session_id is not None:
            self._session_store.revoke(session_id)
        return _json_response(
            HTTPStatus.OK,
            {"status": "logged_out", "correlation_id": correlation_id},
            correlation_id=correlation_id,
            headers=(_clear_session_cookie(),),
        )

    def _handle_create_token(
        self,
        project_key: str,
        payload: object,
        correlation_id: str,
    ) -> AuthRouteResponse:
        try:
            request = CreateProjectApiTokenRequest.model_validate(payload)
        except ValidationError as exc:
            return _validation_error_response(
                "invalid_project_api_token_payload",
                "Invalid project API token payload",
                correlation_id,
                exc,
            )
        issued = issue_project_api_token(
            project_key=project_key,
            label=request.label,
            repository=self._token_repository,
        )
        return _json_response(
            HTTPStatus.CREATED,
            {
                "status": "committed",
                "op_id": request.op_id,
                "operation_kind": "project_api_token_create",
                "correlation_id": correlation_id,
                "token": _token_payload(issued.record),
                "plaintext_token": issued.plaintext_token,
            },
            correlation_id=correlation_id,
        )

    def _handle_revoke_token(
        self,
        project_key: str,
        token_id: str,
        payload: object,
        correlation_id: str,
    ) -> AuthRouteResponse:
        try:
            request = RevokeProjectApiTokenRequest.model_validate(payload)
            self._token_repository.revoke(project_key, token_id)
        except ValidationError as exc:
            return _validation_error_response(
                "invalid_project_api_token_revoke_payload",
                "Invalid project API token revoke payload",
                correlation_id,
                exc,
            )
        except TokenNotFoundError:
            return _error_response(
                HTTPStatus.NOT_FOUND,
                error_code="project_api_token_not_found",
                message="Project API token not found",
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            {
                "status": "committed",
                "op_id": request.op_id,
                "operation_kind": "project_api_token_revoke",
                "correlation_id": correlation_id,
            },
            correlation_id=correlation_id,
        )


def _token_payload(token: ProjectApiToken) -> dict[str, object]:
    return token.model_dump(
        mode="json",
        exclude={"token_hash"},
    )


def _session_payload(session: Session) -> dict[str, object]:
    return session.model_dump(mode="json", exclude={"csrf_token"})


def _session_cookie(session: Session) -> tuple[str, str]:
    max_age = max(0, int((session.expires_at - datetime.now(UTC)).total_seconds()))
    return (
        "Set-Cookie",
        (
            f"{AuthMiddleware.session_cookie_name()}={session.session_id}; "
            f"Max-Age={max_age}; Path=/; HttpOnly; Secure; SameSite=Strict"
        ),
    )


def _clear_session_cookie() -> tuple[str, str]:
    return (
        "Set-Cookie",
        f"{AuthMiddleware.session_cookie_name()}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Strict",
    )


def _session_cookie_from_headers(headers: Mapping[str, str] | None) -> str | None:
    if headers is None:
        return None
    cookie_header = None
    for key, value in headers.items():
        if key.lower() == "cookie":
            cookie_header = value
            break
    if cookie_header is None:
        return None
    for item in cookie_header.split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name == AuthMiddleware.session_cookie_name() and value:
            return value
    return None


def _json_response(
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    correlation_id: str,
    headers: tuple[tuple[str, str], ...] = (),
) -> AuthRouteResponse:
    return AuthRouteResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),) + headers,
    )


def _error_response(
    status: HTTPStatus,
    *,
    error_code: str,
    message: str,
    correlation_id: str,
    detail: object | None = None,
) -> AuthRouteResponse:
    payload: dict[str, object] = {
        "error_code": error_code,
        "error": message,
        "correlation_id": correlation_id,
    }
    if detail is not None:
        payload["detail"] = detail
    return _json_response(status, payload, correlation_id=correlation_id)


def _validation_error_response(
    error_code: str,
    message: str,
    correlation_id: str,
    exc: ValidationError,
) -> AuthRouteResponse:
    return _error_response(
        HTTPStatus.BAD_REQUEST,
        error_code=error_code,
        message=message,
        correlation_id=correlation_id,
        detail=exc.errors(),
    )


def _unauthorized_response(correlation_id: str) -> AuthRouteResponse:
    return _error_response(
        HTTPStatus.UNAUTHORIZED,
        error_code="unauthorized",
        message="Unauthorized",
        correlation_id=correlation_id,
    )
