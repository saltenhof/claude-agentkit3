"""HTTP adapter functions for ownership-transfer endpoints."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.control_plane.models import (
    TakeoverChallengeEchoRequest,
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
    from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
    from agentkit.backend.control_plane_http.responses import HttpResponse

logger = logging.getLogger(__name__)


def dispatch_project_edge_takeover_post(
    *,
    route_path: str,
    payload: object,
    correlation_id: str,
    runtime_service: ControlPlaneRuntimeService,
) -> HttpResponse | None:
    """Dispatch AG3-148 takeover POST routes, or return ``None``."""
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
) -> HttpResponse:
    from agentkit.backend.story_context_manager.errors import (
        IdempotencyMismatchError,
    )

    try:
        request = TakeoverChallengeEchoRequest.model_validate(payload)
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


__all__ = ["dispatch_project_edge_takeover_post"]
