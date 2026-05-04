"""Telemetry SSE routes for the custom control-plane HTTP dispatcher."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.telemetry.sse_stream import (
    ProjectTelemetryEventSource,
    StateBackendProjectTelemetryEventSource,
    iter_project_sse_stream,
    parse_project_topics,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

_CORRELATION_HEADER = "X-Correlation-Id"
_PROJECT_EVENTS_PATH = re.compile(r"^/v1/projects/(?P<project_key>[^/]+)/events$")


@dataclass(frozen=True)
class TelemetryRouteResponse:
    """Serializable response produced by telemetry HTTP routes."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()
    stream: Iterable[bytes] | None = None


class TelemetryRoutes:
    """Route handler for project-scoped telemetry SSE streams."""

    def __init__(self, source: ProjectTelemetryEventSource | None = None) -> None:
        self._source = source or StateBackendProjectTelemetryEventSource()

    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> TelemetryRouteResponse | None:
        """Handle telemetry GET routes or return None."""
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


def _single_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


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
