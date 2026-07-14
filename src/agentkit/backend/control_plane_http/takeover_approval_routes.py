"""Strategist-only cross-project takeover approval read route."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.control_plane_http.responses import (
    HttpResponse,
    _error_response,
    _json_response,
)
from agentkit.backend.exceptions import ConfigError

if TYPE_CHECKING:
    from agentkit.backend.auth.middleware import AuthResult
    from agentkit.backend.control_plane.takeover_approval_repository import (
        TakeoverApprovalReadSource,
    )

_TAKEOVER_APPROVALS_PATH = "/v1/governance/takeover-approvals"


class TakeoverApprovalRoutes:
    """Serve the read-only global approval initial-GET."""

    def __init__(self, source: TakeoverApprovalReadSource) -> None:
        self._source = source

    @staticmethod
    def matches(route_path: str) -> bool:
        """Return whether the path belongs to this read-only route."""
        return route_path == _TAKEOVER_APPROVALS_PATH

    def handle_get(
        self,
        route_path: str,
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> HttpResponse | None:
        """Handle the approval GET or return ``None`` for other paths."""
        if not self.matches(route_path):
            return None
        if auth_result is None or not auth_result.is_human_bff_session:
            return _error_response(
                HTTPStatus.FORBIDDEN,
                error_code="forbidden",
                message="Forbidden",
                correlation_id=correlation_id,
            )
        try:
            response = self._source.list_open_takeover_approvals()
        except (ConfigError, RuntimeError, TypeError, ValueError) as exc:
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="takeover_approvals_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            response.model_dump(mode="json"),
            correlation_id=correlation_id,
        )


__all__ = ["TakeoverApprovalRoutes"]
