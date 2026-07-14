"""Telemetry SSE routes for the custom control-plane HTTP dispatcher."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.telemetry.sse_stream import (
    iter_governance_sse_stream,
    iter_project_sse_stream,
    parse_governance_topics,
    parse_project_topics,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from agentkit.backend.auth.middleware import AuthResult
    from agentkit.backend.telemetry.repository import ProjectTelemetryEventSource

_CORRELATION_HEADER = "X-Correlation-Id"
_PROJECT_EVENTS_PATH = re.compile(r"^/v1/projects/(?P<project_key>[^/]+)/events$")
_GOVERNANCE_EVENTS_PATH = "/v1/events/governance"


@dataclass(frozen=True)
class TelemetryRouteResponse:
    """Serializable response produced by telemetry HTTP routes."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()
    stream: Iterable[bytes] | None = None


class TelemetryRoutes:
    """Route handler for project-scoped telemetry SSE streams.

    Args:
        source: Project-scoped execution-event read port. **Mandatory**: the
            productive adapter lives in ``state_backend.store`` and is injected
            by the composition root (``_build_default_telemetry_routes`` /
            ``build_project_telemetry_event_source``). The telemetry BC never
            self-instantiates a state-backend adapter (AG3-127, single read
            edge / no second read truth).
    """

    def __init__(self, source: ProjectTelemetryEventSource) -> None:
        self._source = source

    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
        auth_result: AuthResult | None = None,
    ) -> TelemetryRouteResponse | None:
        """Handle telemetry GET routes or return None."""
        if route_path == _GOVERNANCE_EVENTS_PATH:
            return self._handle_governance_get(query, correlation_id, auth_result)
        match = _PROJECT_EVENTS_PATH.match(route_path)
        if match is None:
            return None
        try:
            topics = parse_project_topics(_single_query_value(query, "topics"))
        except ValueError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_sse_topics",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return TelemetryRouteResponse(
            status_code=int(HTTPStatus.OK),
            body=b"",
            headers=(
                (_CORRELATION_HEADER, correlation_id),
                ("Content-Type", "text/event-stream; charset=utf-8"),
                ("Cache-Control", "no-cache"),
                ("Connection", "keep-alive"),
            ),
            stream=iter_project_sse_stream(
                project_key=match.group("project_key"),
                source=self._source,
                topics=topics,
            ),
        )

    def _handle_governance_get(
        self,
        query: dict[str, list[str]],
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> TelemetryRouteResponse:
        """Return the strategist-session-only cross-project stream."""
        if auth_result is None or not auth_result.is_human_bff_session:
            return _error_response(
                HTTPStatus.FORBIDDEN,
                error_code="forbidden",
                message="Forbidden",
                correlation_id=correlation_id,
            )
        try:
            topics = parse_governance_topics(_single_query_value(query, "topics"))
        except ValueError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_sse_topics",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return TelemetryRouteResponse(
            status_code=int(HTTPStatus.OK),
            body=b"",
            headers=_stream_headers(correlation_id),
            stream=iter_governance_sse_stream(source=self._source, topics=topics),
        )


def _single_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _stream_headers(correlation_id: str) -> tuple[tuple[str, str], ...]:
    return (
        (_CORRELATION_HEADER, correlation_id),
        ("Content-Type", "text/event-stream; charset=utf-8"),
        ("Cache-Control", "no-cache"),
        ("Connection", "keep-alive"),
    )


def _error_response(
    status: HTTPStatus,
    *,
    error_code: str,
    message: str,
    correlation_id: str,
) -> TelemetryRouteResponse:
    return TelemetryRouteResponse(
        status_code=int(status),
        body=json.dumps(
            {
                "error_code": error_code,
                "error": message,
                "correlation_id": correlation_id,
            },
            sort_keys=True,
        ).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),),
    )


__all__ = ["TelemetryRouteResponse", "TelemetryRoutes"]
