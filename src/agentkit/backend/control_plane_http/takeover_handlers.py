"""HTTP adapter functions for ownership-transfer endpoints."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.auth.middleware import is_ownership_transfer_path
from agentkit.backend.control_plane.models import (
    TakeoverChallengeEchoRequest,
    TakeoverDenyRequest,
    TakeoverRequest,
    op_id_validation_error,
)
from agentkit.backend.control_plane_http import _route_patterns
from agentkit.backend.control_plane_http.responses import (
    _backend_requirement_response,
    _error_response,
    _takeover_result_response,
)
from agentkit.backend.exceptions import ConfigError

if TYPE_CHECKING:
    from agentkit.backend.auth.middleware import AuthResult
    from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
    from agentkit.backend.control_plane_http.responses import HttpResponse

logger = logging.getLogger(__name__)


def dispatch_project_edge_takeover_post(
    *,
    route_path: str,
    payload: object,
    correlation_id: str,
    runtime_service: ControlPlaneRuntimeService,
    auth_result: AuthResult | None = None,
) -> HttpResponse | None:
    """Dispatch AG3-148 takeover POST routes, or return ``None``."""
    if not is_ownership_transfer_path(route_path):
        return None
    if _route_patterns._TAKEOVER_REQUEST_PATTERN.match(route_path):
        return _handle_post_takeover_request(
            payload,
            correlation_id,
            runtime_service=runtime_service,
        )
    if _route_patterns._TAKEOVER_CONFIRM_PATTERN.match(route_path):
        return _handle_post_takeover_confirm(
            payload,
            correlation_id,
            runtime_service=runtime_service,
            auth_result=auth_result,
        )
    if _route_patterns._TAKEOVER_DENY_PATTERN.match(route_path):
        return _handle_post_takeover_deny(
            payload,
            correlation_id,
            runtime_service=runtime_service,
            auth_result=auth_result,
        )
    return None


def _handle_post_takeover_request(
    payload: object,
    correlation_id: str,
    *,
    runtime_service: ControlPlaneRuntimeService,
) -> HttpResponse:
    from agentkit.backend.story_context_manager.errors import (
        IdempotencyMismatchError,
    )

    try:
        request = TakeoverRequest.model_validate(payload)
        result = runtime_service.request_ownership_takeover(request=request)
    except ValidationError as exc:
        return _error_response(
            HTTPStatus.UNPROCESSABLE_ENTITY
            if op_id_validation_error(exc)
            else HTTPStatus.BAD_REQUEST,
            error_code="invalid_takeover_request_payload",
            message="Invalid takeover request payload",
            correlation_id=correlation_id,
            detail=exc.errors(),
        )
    except IdempotencyMismatchError as exc:
        return _error_response(
            HTTPStatus.CONFLICT,
            error_code="idempotency_mismatch",
            message=str(exc),
            correlation_id=correlation_id,
            detail=exc.detail,
        )
    except ConfigError as exc:
        return _backend_requirement_response(
            "ownership_takeover_unavailable", exc, correlation_id
        )
    except RuntimeError as exc:
        logger.warning("Ownership takeover request unavailable: %s", exc)
        return _error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            error_code="ownership_takeover_unavailable",
            message=str(exc),
            correlation_id=correlation_id,
        )
    return _takeover_result_response(result, correlation_id=correlation_id)


def _handle_post_takeover_confirm(
    payload: object,
    correlation_id: str,
    *,
    runtime_service: ControlPlaneRuntimeService,
    auth_result: AuthResult | None,
) -> HttpResponse:
    from agentkit.backend.story_context_manager.errors import (
        IdempotencyMismatchError,
    )

    try:
        if auth_result is None or not auth_result.is_human_bff_session:
            return _error_response(
                HTTPStatus.FORBIDDEN,
                error_code="agent_confirm_forbidden",
                message="Ownership takeover confirm requires a human BFF session",
                correlation_id=correlation_id,
            )
        request = TakeoverChallengeEchoRequest.model_validate(payload)
        request = request.model_copy(update={"principal_type": "human_bff_session"})
        result = runtime_service.confirm_ownership_takeover(request=request)
    except ValidationError as exc:
        return _error_response(
            HTTPStatus.UNPROCESSABLE_ENTITY
            if op_id_validation_error(exc)
            else HTTPStatus.BAD_REQUEST,
            error_code="invalid_takeover_confirm_payload",
            message="Invalid takeover confirm payload",
            correlation_id=correlation_id,
            detail=exc.errors(),
        )
    except IdempotencyMismatchError as exc:
        return _error_response(
            HTTPStatus.CONFLICT,
            error_code="idempotency_mismatch",
            message=str(exc),
            correlation_id=correlation_id,
            detail=exc.detail,
        )
    except ConfigError as exc:
        return _backend_requirement_response(
            "ownership_takeover_unavailable", exc, correlation_id
        )
    except RuntimeError as exc:
        logger.warning("Ownership takeover confirm unavailable: %s", exc)
        return _error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            error_code="ownership_takeover_unavailable",
            message=str(exc),
            correlation_id=correlation_id,
        )
    return _takeover_result_response(result, correlation_id=correlation_id)


def _handle_post_takeover_deny(
    payload: object,
    correlation_id: str,
    *,
    runtime_service: ControlPlaneRuntimeService,
    auth_result: AuthResult | None,
) -> HttpResponse:
    from agentkit.backend.story_context_manager.errors import (
        IdempotencyMismatchError,
    )

    try:
        if auth_result is None or not auth_result.is_human_bff_session:
            return _error_response(
                HTTPStatus.FORBIDDEN,
                error_code="agent_deny_forbidden",
                message="Ownership takeover deny requires a human BFF session",
                correlation_id=correlation_id,
            )
        request = TakeoverDenyRequest.model_validate(payload)
        request = request.model_copy(update={"principal_type": "human_bff_session"})
        result = runtime_service.deny_ownership_takeover(request=request)
    except ValidationError as exc:
        return _error_response(
            HTTPStatus.UNPROCESSABLE_ENTITY
            if op_id_validation_error(exc)
            else HTTPStatus.BAD_REQUEST,
            error_code="invalid_takeover_deny_payload",
            message="Invalid takeover deny payload",
            correlation_id=correlation_id,
            detail=exc.errors(),
        )
    except IdempotencyMismatchError as exc:
        return _error_response(
            HTTPStatus.CONFLICT,
            error_code="idempotency_mismatch",
            message=str(exc),
            correlation_id=correlation_id,
            detail=exc.detail,
        )
    except ConfigError as exc:
        return _backend_requirement_response(
            "ownership_takeover_unavailable", exc, correlation_id
        )
    except RuntimeError as exc:
        logger.warning("Ownership takeover deny unavailable: %s", exc)
        return _error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            error_code="ownership_takeover_unavailable",
            message=str(exc),
            correlation_id=correlation_id,
        )
    return _takeover_result_response(result, correlation_id=correlation_id)


__all__ = ["dispatch_project_edge_takeover_post"]
