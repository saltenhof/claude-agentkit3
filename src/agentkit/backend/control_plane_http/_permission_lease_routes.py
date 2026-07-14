"""HTTP route handler for central CCAG permission leases."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.control_plane.models import (
    PermissionLeaseConsumeRequest,
    PermissionLeaseGrantRequest,
    PermissionLeaseView,
)
from agentkit.backend.control_plane_http._permission_route_common import forbidden
from agentkit.backend.control_plane_http.responses import HttpResponse, _error_response, _json_response
from agentkit.backend.governance.ccag.permission_commands import GrantPermissionLeaseCommand

if TYPE_CHECKING:
    from agentkit.backend.auth.middleware import AuthResult
    from agentkit.backend.governance.ccag.permission_service import PermissionService


class PermissionLeaseRoutes:
    """Serve strategist grant and hook consume operations."""

    path = "/v1/governance/permission-leases"

    def __init__(self, service: PermissionService) -> None:
        self._service = service

    def handle_post(
        self, payload: object, correlation_id: str, auth: AuthResult | None
    ) -> HttpResponse:
        """Grant or consume after role authorization and before mutation."""
        operation = payload.get("operation") if isinstance(payload, dict) else None
        try:
            if operation == "grant":
                if auth is None or not auth.is_human_bff_session:
                    return forbidden(correlation_id, "Granting a permission lease requires a human BFF session")
                grant_request = PermissionLeaseGrantRequest.model_validate(payload)
                grant_command = GrantPermissionLeaseCommand.model_validate(
                    grant_request.model_dump(exclude={"operation"})
                )
                record = self._service.grant(grant_command)
                status = HTTPStatus.CREATED
            else:
                if auth is None or auth.auth_kind != "project_api_token":
                    return forbidden(correlation_id, "Consuming a permission lease requires a project token")
                consume_request = PermissionLeaseConsumeRequest.model_validate(payload)
                current = self._service.read_lease(consume_request.lease_id)
                if current is None or current.project_key != auth.project_key:
                    return forbidden(correlation_id, "Permission lease is outside the project token scope")
                record = self._service.consume(consume_request.lease_id)
                status = HTTPStatus.OK
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY, error_code="invalid_permission_lease_payload",
                message="Invalid permission lease payload", correlation_id=correlation_id,
                detail=exc.errors(),
            )
        return _json_response(
            status, PermissionLeaseView.model_validate(record.model_dump()).model_dump(mode="json"),
            correlation_id=correlation_id,
        )


__all__ = ["PermissionLeaseRoutes"]
