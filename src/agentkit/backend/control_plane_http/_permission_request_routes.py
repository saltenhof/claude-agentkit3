"""HTTP route handler for central CCAG permission requests."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.control_plane.models import (
    PermissionRequestOpenRequest,
    PermissionRequestResolveRequest,
    PermissionRequestView,
)
from agentkit.backend.control_plane_http._permission_request_read import read_permission_requests
from agentkit.backend.control_plane_http._permission_route_common import forbidden
from agentkit.backend.control_plane_http.responses import (
    HttpResponse,
    _error_response,
    _json_response,
)
from agentkit.backend.governance.ccag.permission_commands import (
    OpenPermissionRequestCommand,
    ResolvePermissionRequestCommand,
)

if TYPE_CHECKING:
    from agentkit.backend.auth.middleware import AuthResult
    from agentkit.backend.governance.ccag.permission_service import PermissionService


class PermissionRequestRoutes:
    """Serve open/read/resolve operations for permission requests."""

    path = "/v1/governance/permission-requests"

    def __init__(self, service: PermissionService) -> None:
        self._service = service

    def handle_get(
        self,
        query: dict[str, list[str]],
        correlation_id: str,
        auth: AuthResult | None,
    ) -> HttpResponse:
        """Read only the project-token's own canonical requests."""
        return read_permission_requests(self._service, query, correlation_id, auth)

    def handle_post(self, payload: object, correlation_id: str, auth: AuthResult | None) -> HttpResponse:
        """Open as hook or resolve as strategist, checking auth before mutation."""
        operation = payload.get("operation") if isinstance(payload, dict) else None
        try:
            if operation == "open":
                if auth is None or auth.auth_kind != "project_api_token":
                    return forbidden(correlation_id, "Opening a permission request requires a project token")
                open_request = PermissionRequestOpenRequest.model_validate(payload)
                if auth.project_key != open_request.project_key:
                    return forbidden(correlation_id, "Project token scope does not match request")
                open_command = OpenPermissionRequestCommand.model_validate(
                    open_request.model_dump(exclude={"operation"})
                )
                record = self._service.open(open_command)
                status = HTTPStatus.CREATED
            else:
                if auth is None or not auth.is_human_bff_session:
                    return forbidden(correlation_id, "Resolving a permission request requires a human BFF session")
                resolve_request = PermissionRequestResolveRequest.model_validate(payload)
                resolve_command = ResolvePermissionRequestCommand.model_validate(
                    resolve_request.model_dump(exclude={"operation"})
                )
                record = self._service.resolve(resolve_command)
                status = HTTPStatus.OK
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code="invalid_permission_request_payload",
                message="Invalid permission request payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        body = PermissionRequestView.model_validate(record.model_dump())
        return _json_response(
            status, body.model_dump(mode="json"), correlation_id=correlation_id
        )


__all__ = ["PermissionRequestRoutes"]
