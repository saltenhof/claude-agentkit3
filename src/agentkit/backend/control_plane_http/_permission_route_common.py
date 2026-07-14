"""Shared response mapping for CCAG permission HTTP routes."""

from __future__ import annotations

from http import HTTPStatus

from agentkit.backend.control_plane_http.responses import HttpResponse, _error_response
from agentkit.backend.governance.ccag.permission_errors import (
    PermissionConflictError,
    PermissionLeaseExhaustedError,
    PermissionLeaseExpiredError,
    PermissionNotFoundError,
)


def forbidden(correlation_id: str, message: str) -> HttpResponse:
    """Return a stable strategist/hook authorization failure."""
    return _error_response(
        HTTPStatus.FORBIDDEN, error_code="forbidden", message=message,
        correlation_id=correlation_id,
    )


def permission_error(exc: Exception, correlation_id: str) -> HttpResponse:
    """Map a named permission fault to its stable HTTP contract."""
    if isinstance(exc, PermissionNotFoundError):
        status, code = HTTPStatus.NOT_FOUND, "permission_state_not_found"
    elif isinstance(exc, PermissionConflictError):
        status, code = HTTPStatus.CONFLICT, "permission_state_conflict"
    elif isinstance(exc, PermissionLeaseExpiredError):
        status, code = HTTPStatus.CONFLICT, "permission_lease_expired"
    elif isinstance(exc, PermissionLeaseExhaustedError):
        status, code = HTTPStatus.CONFLICT, "permission_lease_exhausted"
    else:
        status, code = HTTPStatus.SERVICE_UNAVAILABLE, "permission_state_unavailable"
    return _error_response(
        status, error_code=code, message=str(exc), correlation_id=correlation_id
    )


__all__ = ["forbidden", "permission_error"]
