"""HTTP dispatch boundary for the global takeover frontend surfaces."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.control_plane_http.responses import (
    HttpResponse,
    _error_response,
    _telemetry_response_to_http_response,
)

if TYPE_CHECKING:
    from agentkit.backend.auth.middleware import AuthResult
    from agentkit.backend.control_plane_http.takeover_approval_routes import (
        TakeoverApprovalRoutes,
    )
    from agentkit.backend.telemetry.http.routes import TelemetryRoutes


class TakeoverFrontendDispatcher:
    """Compose approval initial-GET and governance SSE HTTP routes."""

    def __init__(
        self,
        approval_routes: TakeoverApprovalRoutes,
        telemetry_routes: TelemetryRoutes,
    ) -> None:
        self._approval_routes = approval_routes
        self._telemetry_routes = telemetry_routes

    def handle(
        self,
        method: str,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> HttpResponse | None:
        """Dispatch takeover frontend routes or abstain."""
        if method != "GET":
            return self._method_not_allowed(route_path, correlation_id)
        approval = self._approval_routes.handle_get(
            route_path,
            correlation_id,
            auth_result,
        )
        if approval is not None:
            return approval
        if route_path != "/v1/events/governance":
            return None
        telemetry = self._telemetry_routes.handle_get(
            route_path,
            query,
            correlation_id,
            auth_result,
        )
        if telemetry is None:
            return None
        return _telemetry_response_to_http_response(telemetry)

    def _method_not_allowed(
        self,
        route_path: str,
        correlation_id: str,
    ) -> HttpResponse | None:
        """Return the read-only approval route's deterministic 405."""
        if not self._approval_routes.matches(route_path):
            return None
        return _error_response(
            HTTPStatus.METHOD_NOT_ALLOWED,
            error_code="method_not_allowed",
            message="Method not allowed",
            correlation_id=correlation_id,
        )


__all__ = ["TakeoverFrontendDispatcher"]
