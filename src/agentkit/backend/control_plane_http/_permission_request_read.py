"""Project-token read handler for central CCAG permission requests."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import PermissionRequestsResponse, PermissionRequestView
from agentkit.backend.control_plane_http._permission_route_common import forbidden
from agentkit.backend.control_plane_http.responses import (
    HttpResponse,
    _error_response,
    _json_response,
    _single_query_value,
)

if TYPE_CHECKING:
    from agentkit.backend.auth.middleware import AuthResult
    from agentkit.backend.governance.ccag.permission_records import PermissionRequestRecord
    from agentkit.backend.governance.ccag.permission_service import PermissionService


def read_permission_requests(
    service: PermissionService,
    query: dict[str, list[str]],
    correlation_id: str,
    auth: AuthResult | None,
) -> HttpResponse:
    """Read only the project-token's own canonical requests."""
    project_key = _single_query_value(query, "project_key")
    if (
        not project_key
        or auth is None
        or auth.auth_kind != "project_api_token"
        or auth.project_key != project_key
    ):
        return forbidden(
            correlation_id, "Permission request reads require the matching project token"
        )
    request_id = _single_query_value(query, "request_id")
    records: tuple[PermissionRequestRecord, ...]
    if request_id:
        record = service.read(request_id)
        records = () if record is None else (record,)
        if record is not None and record.project_key != project_key:
            return forbidden(correlation_id, "Permission request belongs to another project")
    else:
        story_id = _single_query_value(query, "story_id")
        run_id = _single_query_value(query, "run_id")
        if not story_id or not run_id:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_permission_request_query",
                message="project_key, story_id and run_id are required",
                correlation_id=correlation_id,
            )
        records = service.list_for_run(project_key, story_id, run_id)
    body = PermissionRequestsResponse(
        requests=tuple(PermissionRequestView.model_validate(item.model_dump()) for item in records)
    )
    return _json_response(
        HTTPStatus.OK, body.model_dump(mode="json"), correlation_id=correlation_id
    )


__all__ = ["read_permission_requests"]
