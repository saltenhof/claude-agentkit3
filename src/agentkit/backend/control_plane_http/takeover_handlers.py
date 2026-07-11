"""HTTP adapter functions for ownership-transfer endpoints."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.auth.middleware import is_ownership_transfer_path
from agentkit.backend.control_plane.models import (
    AdminTakeoverReconcileClearRequest,
    TakeoverConfirmRequest,
    TakeoverDenyRequest,
    TakeoverReconcileWorktreeRequest,
    TakeoverRequest,
    op_id_validation_error,
)
from agentkit.backend.control_plane.runtime import TakeoverConfirmCommand, TakeoverDenyCommand
from agentkit.backend.control_plane_http import _route_patterns
from agentkit.backend.control_plane_http.responses import (
    _backend_requirement_response,
    _error_response,
    _takeover_result_response,
)
from agentkit.backend.exceptions import ConfigError
from agentkit.backend.governance.principal_capabilities.principals import Principal

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
            auth_result=auth_result,
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
    if _route_patterns._TAKEOVER_RECONCILE_CLEAR_PATTERN.match(route_path):
        return _handle_post_takeover_reconcile_clear(
            payload,
            correlation_id,
            runtime_service=runtime_service,
            auth_result=auth_result,
        )
    reconcile_match = _route_patterns._TAKEOVER_RECONCILE_WORKTREE_PATTERN.match(
        route_path
    )
    if reconcile_match:
        return _handle_post_takeover_reconcile_worktree(
            reconcile_match.group("run_id"),
            payload,
            correlation_id,
            runtime_service=runtime_service,
            auth_result=auth_result,
        )
    return None


def _handle_post_takeover_reconcile_worktree(
    run_id: str,
    payload: object,
    correlation_id: str,
    *,
    runtime_service: ControlPlaneRuntimeService,
    auth_result: AuthResult | None,
) -> HttpResponse:
    """Handle the official new-owner reconcile result contract."""

    from agentkit.backend.story_context_manager.errors import (
        IdempotencyMismatchError,
    )

    try:
        request = TakeoverReconcileWorktreeRequest.model_validate(payload)
        project_fence = _project_key_fence(
            request_project_key=request.project_key,
            auth_result=auth_result,
            correlation_id=correlation_id,
        )
        if project_fence is not None:
            return project_fence
        if auth_result is not None and auth_result.session_id is not None:
            request = request.model_copy(
                update={"session_id": auth_result.session_id}
            )
        result = runtime_service.reconcile_takeover_worktree(run_id, request)
    except ValidationError as exc:
        return _error_response(
            HTTPStatus.UNPROCESSABLE_ENTITY
            if op_id_validation_error(exc)
            else HTTPStatus.BAD_REQUEST,
            error_code="invalid_takeover_reconcile_payload",
            message="Invalid takeover reconcile payload",
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
        logger.warning("Takeover reconcile unavailable: %s", exc)
        return _error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            error_code="ownership_takeover_unavailable",
            message=str(exc),
            correlation_id=correlation_id,
        )
    return _takeover_result_response(result, correlation_id=correlation_id)


def _handle_post_takeover_request(
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
        request = TakeoverRequest.model_validate(payload)
        principal = _takeover_request_principal(auth_result=auth_result)
        if principal is None:
            return _error_response(
                HTTPStatus.FORBIDDEN,
                error_code="invalid_takeover_principal",
                message="Ownership takeover request requires an attested canonical principal",
                correlation_id=correlation_id,
            )
        project_fence = _project_key_fence(
            request_project_key=request.project_key,
            auth_result=auth_result,
            correlation_id=correlation_id,
        )
        if project_fence is not None:
            return project_fence
        request = request.model_copy(update={"principal_type": principal})
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
        if (
            auth_result is None
            or not auth_result.is_human_bff_session
            or auth_result.session_id is None
        ):
            return _error_response(
                HTTPStatus.FORBIDDEN,
                error_code="agent_confirm_forbidden",
                message="Ownership takeover confirm requires a human BFF session",
                correlation_id=correlation_id,
            )
        request = TakeoverConfirmRequest.model_validate(payload)
        project_fence = _project_key_fence(
            request_project_key=request.project_key,
            auth_result=auth_result,
            correlation_id=correlation_id,
        )
        if project_fence is not None:
            return project_fence
        command = TakeoverConfirmCommand(
            request=request,
            confirmed_by_session_id=auth_result.session_id,
            confirmed_by_principal=Principal.HUMAN_CLI,
        )
        result = runtime_service.confirm_ownership_takeover(command=command)
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
        if (
            auth_result is None
            or not auth_result.is_human_bff_session
            or auth_result.session_id is None
        ):
            return _error_response(
                HTTPStatus.FORBIDDEN,
                error_code="agent_deny_forbidden",
                message="Ownership takeover deny requires a human BFF session",
                correlation_id=correlation_id,
            )
        request = TakeoverDenyRequest.model_validate(payload)
        project_fence = _project_key_fence(
            request_project_key=request.project_key,
            auth_result=auth_result,
            correlation_id=correlation_id,
        )
        if project_fence is not None:
            return project_fence
        command = TakeoverDenyCommand(
            request=request,
            denied_by_session_id=auth_result.session_id,
            denied_by_principal=Principal.HUMAN_CLI,
        )
        result = runtime_service.deny_ownership_takeover(command=command)
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


def _handle_post_takeover_reconcile_clear(
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
        if (
            auth_result is None
            or not auth_result.is_human_bff_session
            or auth_result.session_id is None
        ):
            return _error_response(
                HTTPStatus.FORBIDDEN,
                error_code="takeover_reconcile_clear_forbidden",
                message="Takeover reconcile clear requires a human BFF session",
                correlation_id=correlation_id,
            )
        request = AdminTakeoverReconcileClearRequest.model_validate(payload)
        project_fence = _project_key_fence(
            request_project_key=request.project_key,
            auth_result=auth_result,
            correlation_id=correlation_id,
        )
        if project_fence is not None:
            return project_fence
        request = request.model_copy(
            update={
                "session_id": auth_result.session_id,
                "principal_type": "human_bff_session",
            }
        )
        result = runtime_service.clear_takeover_reconcile_obligation(request=request)
    except ValidationError as exc:
        return _error_response(
            HTTPStatus.UNPROCESSABLE_ENTITY
            if op_id_validation_error(exc)
            else HTTPStatus.BAD_REQUEST,
            error_code="invalid_takeover_reconcile_clear_payload",
            message="Invalid takeover reconcile clear payload",
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
        logger.warning("Takeover reconcile clear unavailable: %s", exc)
        return _error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            error_code="ownership_takeover_unavailable",
            message=str(exc),
            correlation_id=correlation_id,
        )
    return _takeover_result_response(result, correlation_id=correlation_id)


def _project_key_fence(
    *,
    request_project_key: str,
    auth_result: AuthResult | None,
    correlation_id: str,
) -> HttpResponse | None:
    # Project API tokens are normally fenced earlier by AuthMiddleware
    # (missing attested project -> 401; token/project mismatch -> 403). The
    # takeover fence still fails closed on null scope as defense-in-depth for
    # optional-auth deployments and human strategist sessions.
    if auth_result is None or auth_result.project_key is None:
        return _error_response(
            HTTPStatus.FORBIDDEN,
            error_code="project_scope_mismatch",
            message="Ownership takeover requires an attested project scope",
            correlation_id=correlation_id,
        )
    if request_project_key == auth_result.project_key:
        return None
    return _error_response(
        HTTPStatus.FORBIDDEN,
        error_code="project_scope_mismatch",
        message="Request project_key does not match the authenticated project scope",
        correlation_id=correlation_id,
    )


def _takeover_request_principal(
    *,
    auth_result: AuthResult | None,
) -> str | None:
    if auth_result is None:
        return None
    if auth_result.auth_kind == "project_api_token":
        return Principal.INTERACTIVE_AGENT.value
    if auth_result.is_human_bff_session:
        return Principal.HUMAN_CLI.value
    return None


__all__ = ["dispatch_project_edge_takeover_post"]
