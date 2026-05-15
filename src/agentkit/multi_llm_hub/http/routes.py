"""Multi-LLM-Hub routes for the existing control-plane HTTP dispatcher.

``ControlPlaneApplication`` registers this adapter for the project-neutral
``/v1/hub`` surface. The routes proxy to the external Hub and do not implement
LLM routing, quota, or cost policies.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentkit.multi_llm_hub.config import load_multi_llm_hub_config
from agentkit.multi_llm_hub.entities import HubBackendName
from agentkit.multi_llm_hub.errors import HubSessionNotFoundError, HubUnavailableError, MultiLlmHubError
from agentkit.multi_llm_hub.sse_stream import iter_hub_sse_stream, parse_hub_topics

if TYPE_CHECKING:
    from collections.abc import Iterable

    from agentkit.multi_llm_hub.client import HubClientProtocol
    from agentkit.multi_llm_hub.entities import HubBackendMetric, HubHealth, HubSession

_CORRELATION_HEADER = "X-Correlation-Id"
_HUB_MESSAGES_PATH = re.compile(r"^/v1/hub/sessions/(?P<session_id>[^/]+)/messages$")
_HUB_RELEASE_PATH = re.compile(r"^/v1/hub/sessions/(?P<session_id>[^/]+)/release$")


@dataclass(frozen=True)
class MultiLlmHubRouteResponse:
    """Serializable response produced by the Multi-LLM-Hub HTTP adapter."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()
    stream: Iterable[bytes] | None = None


class AcquireHubSessionRequest(BaseModel):
    """Request body for Hub session acquire."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner: str
    description: str
    llms: list[HubBackendName] = Field(default_factory=list)
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")


class SendHubMessageRequest(BaseModel):
    """Request body for Hub send proxy operations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    token: str
    message: str | None = None
    target: HubBackendName | None = None
    targets: dict[HubBackendName, str] | None = None
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")


class ReleaseHubSessionRequest(BaseModel):
    """Request body for Hub session release."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    token: str
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")


class MultiLlmHubRoutes:
    """Route handler for the project-neutral Multi-LLM-Hub surface."""

    def __init__(self, client: HubClientProtocol | None = None) -> None:
        if client is None:
            from agentkit.multi_llm_hub.client import HubClient

            config = load_multi_llm_hub_config()
            client = HubClient(config.base_url)
        self._client = client

    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> MultiLlmHubRouteResponse | None:
        """Handle Hub GET routes or return None."""

        if route_path == "/v1/hub/status":
            return self._handle_status(correlation_id)
        if route_path == "/v1/hub/sessions":
            return self._handle_sessions(correlation_id)
        if route_path == "/v1/events/hub":
            return self._handle_hub_events(query, correlation_id)
        return None

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> MultiLlmHubRouteResponse | None:
        """Handle Hub POST routes or return None."""

        if route_path == "/v1/hub/sessions":
            return self._handle_acquire(payload, correlation_id)

        message_match = _HUB_MESSAGES_PATH.match(route_path)
        if message_match is not None:
            return self._handle_send(message_match.group("session_id"), payload, correlation_id)

        release_match = _HUB_RELEASE_PATH.match(route_path)
        if release_match is not None:
            return self._handle_release(release_match.group("session_id"), payload, correlation_id)
        return None

    def _handle_status(self, correlation_id: str) -> MultiLlmHubRouteResponse:
        try:
            health = self._client.health()
            metrics = self._client.pool_status()
        except HubUnavailableError as exc:
            return _unavailable_response(str(exc), correlation_id)
        return _json_response(
            HTTPStatus.OK,
            {
                "health": health.model_dump(mode="json"),
                "backends": [metric.model_dump(mode="json") for metric in metrics],
            },
            correlation_id=correlation_id,
        )

    def _handle_sessions(self, correlation_id: str) -> MultiLlmHubRouteResponse:
        try:
            sessions = self._client.list_sessions(include_inactive=True)
        except HubUnavailableError as exc:
            return _unavailable_response(str(exc), correlation_id)
        return _json_response(
            HTTPStatus.OK,
            {"sessions": [session.model_dump(mode="json") for session in sessions]},
            correlation_id=correlation_id,
        )

    def _handle_hub_events(
        self,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> MultiLlmHubRouteResponse:
        try:
            topics = parse_hub_topics(_single_query_value(query, "topics"))
        except ValueError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_sse_topics",
                message=str(exc),
                correlation_id=correlation_id,
            )
        source = _HubClientSseSnapshotSource(self._client)
        return MultiLlmHubRouteResponse(
            status_code=int(HTTPStatus.OK),
            body=b"",
            headers=(
                (_CORRELATION_HEADER, correlation_id),
                ("Content-Type", "text/event-stream; charset=utf-8"),
                ("Cache-Control", "no-cache"),
                ("Connection", "keep-alive"),
            ),
            stream=iter_hub_sse_stream(source=source, topics=topics),
        )

    def _handle_acquire(
        self,
        payload: object,
        correlation_id: str,
    ) -> MultiLlmHubRouteResponse:
        try:
            request = AcquireHubSessionRequest.model_validate(payload)
        except ValidationError as exc:
            return _validation_error_response("invalid_hub_acquire_payload", correlation_id, exc)
        try:
            lease = self._client.acquire(
                owner=request.owner,
                description=request.description,
                llms=request.llms,
            )
        except HubUnavailableError as exc:
            return _unavailable_response(str(exc), correlation_id)
        except MultiLlmHubError as exc:
            return _hub_error_response(str(exc), correlation_id)
        return _mutation_response(
            HTTPStatus.CREATED,
            request.op_id,
            "hub_session_acquire",
            {"lease": lease.model_dump(mode="json")},
            correlation_id,
        )

    def _handle_send(
        self,
        session_id: str,
        payload: object,
        correlation_id: str,
    ) -> MultiLlmHubRouteResponse:
        try:
            request = SendHubMessageRequest.model_validate(payload)
        except ValidationError as exc:
            return _validation_error_response("invalid_hub_send_payload", correlation_id, exc)
        try:
            messages = self._client.send(
                session_id=session_id,
                token=request.token,
                message=request.message,
                target=request.target,
                targets=request.targets,
            )
        except HubSessionNotFoundError as exc:
            return _not_found_response(str(exc), correlation_id)
        except HubUnavailableError as exc:
            return _unavailable_response(str(exc), correlation_id)
        except MultiLlmHubError as exc:
            return _hub_error_response(str(exc), correlation_id)
        return _mutation_response(
            HTTPStatus.OK,
            request.op_id,
            "hub_message_send",
            {"messages": {backend: message.model_dump(mode="json") for backend, message in messages.items()}},
            correlation_id,
        )

    def _handle_release(
        self,
        session_id: str,
        payload: object,
        correlation_id: str,
    ) -> MultiLlmHubRouteResponse:
        try:
            request = ReleaseHubSessionRequest.model_validate(payload)
        except ValidationError as exc:
            return _validation_error_response("invalid_hub_release_payload", correlation_id, exc)
        try:
            self._client.release(session_id=session_id, token=request.token)
        except HubSessionNotFoundError as exc:
            return _not_found_response(str(exc), correlation_id)
        except HubUnavailableError as exc:
            return _unavailable_response(str(exc), correlation_id)
        except MultiLlmHubError as exc:
            return _hub_error_response(str(exc), correlation_id)
        return _mutation_response(
            HTTPStatus.OK,
            request.op_id,
            "hub_session_release",
            {"session_id": session_id},
            correlation_id,
        )


def _mutation_response(
    status: HTTPStatus,
    op_id: str,
    operation_kind: str,
    payload: dict[str, object],
    correlation_id: str,
) -> MultiLlmHubRouteResponse:
    return _json_response(
        status,
        {
            "status": "committed",
            "op_id": op_id,
            "operation_kind": operation_kind,
            "correlation_id": correlation_id,
            **payload,
        },
        correlation_id=correlation_id,
    )


class _HubClientSseSnapshotSource:
    def __init__(self, client: HubClientProtocol) -> None:
        self._client = client

    def backend_status(self) -> tuple[HubHealth, list[HubBackendMetric]]:
        return self._client.health(), self._client.pool_status()

    def sessions(self) -> list[HubSession]:
        return self._client.list_sessions(include_inactive=True)


def _single_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _json_response(
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    correlation_id: str,
) -> MultiLlmHubRouteResponse:
    return MultiLlmHubRouteResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),),
    )


def _validation_error_response(
    error_code: str,
    correlation_id: str,
    exc: ValidationError,
) -> MultiLlmHubRouteResponse:
    return _error_response(
        HTTPStatus.BAD_REQUEST,
        error_code=error_code,
        message="Invalid Hub request payload",
        correlation_id=correlation_id,
        detail=exc.errors(),
    )


def _unavailable_response(message: str, correlation_id: str) -> MultiLlmHubRouteResponse:
    return _error_response(
        HTTPStatus.SERVICE_UNAVAILABLE,
        error_code="hub_unavailable",
        message=message,
        correlation_id=correlation_id,
    )


def _not_found_response(message: str, correlation_id: str) -> MultiLlmHubRouteResponse:
    return _error_response(
        HTTPStatus.NOT_FOUND,
        error_code="hub_session_not_found",
        message=message,
        correlation_id=correlation_id,
    )


def _hub_error_response(message: str, correlation_id: str) -> MultiLlmHubRouteResponse:
    return _error_response(
        HTTPStatus.BAD_GATEWAY,
        error_code="hub_error",
        message=message,
        correlation_id=correlation_id,
    )


def _error_response(
    status: HTTPStatus,
    *,
    error_code: str,
    message: str,
    correlation_id: str,
    detail: object | None = None,
) -> MultiLlmHubRouteResponse:
    payload: dict[str, object] = {
        "error_code": error_code,
        "error": message,
        "correlation_id": correlation_id,
    }
    if detail is not None:
        payload["detail"] = detail
    return _json_response(status, payload, correlation_id=correlation_id)
