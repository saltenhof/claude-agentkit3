"""Control-plane route bundle for central CCAG permission state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.control_plane_http._permission_lease_routes import PermissionLeaseRoutes
from agentkit.backend.control_plane_http._permission_request_routes import PermissionRequestRoutes
from agentkit.backend.control_plane_http._permission_route_common import permission_error
from agentkit.backend.exceptions import ConfigError
from agentkit.backend.governance.ccag.permission_errors import PermissionStateError

if TYPE_CHECKING:
    from agentkit.backend.auth.middleware import AuthResult
    from agentkit.backend.control_plane_http.responses import HttpResponse
    from agentkit.backend.governance.ccag.permission_service import PermissionService


class PermissionRoutes:
    """Dispatch the two CCAG permission endpoint families."""

    def __init__(self, service: PermissionService) -> None:
        self._requests = PermissionRequestRoutes(service)
        self._leases = PermissionLeaseRoutes(service)

    def handle_get(
        self, route_path: str, query: dict[str, list[str]], correlation_id: str,
        auth: AuthResult | None,
    ) -> HttpResponse | None:
        """Dispatch the permission-request read endpoint."""
        if route_path != self._requests.path:
            return None
        try:
            return self._requests.handle_get(query, correlation_id, auth)
        except (ConfigError, PermissionStateError, RuntimeError, TypeError, ValueError) as exc:
            return permission_error(exc, correlation_id)

    def handle_post(
        self, route_path: str, payload: object, correlation_id: str,
        auth: AuthResult | None,
    ) -> HttpResponse | None:
        """Dispatch request/lease mutations with visible fault mapping."""
        try:
            if route_path == self._requests.path:
                return self._requests.handle_post(payload, correlation_id, auth)
            if route_path == self._leases.path:
                return self._leases.handle_post(payload, correlation_id, auth)
        except (ConfigError, PermissionStateError, RuntimeError, TypeError, ValueError) as exc:
            return permission_error(exc, correlation_id)
        return None


__all__ = ["PermissionRoutes"]
