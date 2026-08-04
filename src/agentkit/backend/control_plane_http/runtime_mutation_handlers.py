"""HTTP translation for control-plane runtime mutations."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.control_plane.models import (
    AdminAbortRequest,
    ClosureCompleteRequest,
    EdgeCommandResultRequest,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
    op_id_validation_error,
)
from agentkit.backend.control_plane.runtime import (
    OperationNotAbortableError,
    OperationNotFoundError,
)
from agentkit.backend.control_plane_http.responses import (
    HttpResponse,
    _backend_requirement_response,
    _edge_command_result_response,
    _error_response,
    _json_response,
    _mutation_result_response,
)
from agentkit.backend.exceptions import ConfigError

if TYPE_CHECKING:
    from agentkit.backend.auth.middleware import AuthResult
    from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService

logger = logging.getLogger(__name__)


class _RuntimeMutationHandlers:
    """Translate runtime mutation requests into stable HTTP responses."""

    if TYPE_CHECKING:
        _runtime_service: ControlPlaneRuntimeService

    def _handle_post_phase_mutation(
        self,
        *,
        payload: object,
        run_id: str,
        phase: str,
        action: str,
        correlation_id: str,
    ) -> HttpResponse:
        from agentkit.backend.story_context_manager.errors import (
            IdempotencyMismatchError,
        )

        try:
            request = PhaseMutationRequest.model_validate(payload)
            if action == "start":
                result = self._runtime_service.start_phase(
                    run_id=run_id,
                    phase=phase,
                    request=request,
                )
            elif action == "complete":
                result = self._runtime_service.complete_phase(
                    run_id=run_id,
                    phase=phase,
                    request=request,
                )
            elif action == "fail":
                result = self._runtime_service.fail_phase(
                    run_id=run_id,
                    phase=phase,
                    request=request,
                )
            else:
                # AG3-130: resume a PAUSED phase; the core drives the pipeline
                # engine's resume path server-side (FK-45, FK-91 §91.1a).
                result = self._runtime_service.resume_phase(
                    run_id=run_id,
                    phase=phase,
                    request=request,
                )
        except ValidationError as exc:
            # AG3-140 (FK-91 §91.1a Rule 5, AC1): a missing/empty op_id fails
            # closed with 422, distinct from an ordinary 400 payload-shape defect.
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY
                if op_id_validation_error(exc)
                else HTTPStatus.BAD_REQUEST,
                error_code="invalid_phase_mutation_payload",
                message="Invalid phase mutation payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except IdempotencyMismatchError as exc:
            # AG3-140 finding 3 (FK-91 §91.1a Rule 5): a terminal op_id replayed
            # with a DIFFERENT phase/action/body is fail-closed 409, not a wrong
            # replay of the stored result.
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="idempotency_mismatch",
                message=str(exc),
                correlation_id=correlation_id,
                detail=exc.detail,
            )
        except ConfigError as exc:
            return _backend_requirement_response(
                "phase_mutation_unavailable", exc, correlation_id
            )
        except RuntimeError as exc:
            logger.warning("Control-plane phase mutation unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="phase_mutation_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _mutation_result_response(result, correlation_id=correlation_id)

    def _handle_post_closure_complete(
        self,
        *,
        payload: object,
        run_id: str,
        correlation_id: str,
    ) -> HttpResponse:
        from agentkit.backend.story_context_manager.errors import (
            IdempotencyMismatchError,
        )

        try:
            request = ClosureCompleteRequest.model_validate(payload)
            result = self._runtime_service.complete_closure(
                run_id=run_id,
                request=request,
            )
        except ValidationError as exc:
            # AG3-140 (FK-91 §91.1a Rule 5, AC1): a missing/empty op_id fails
            # closed with 422, distinct from an ordinary 400 payload-shape defect.
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY
                if op_id_validation_error(exc)
                else HTTPStatus.BAD_REQUEST,
                error_code="invalid_closure_payload",
                message="Invalid closure payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except IdempotencyMismatchError as exc:
            # AG3-140 finding 3: a terminal op_id replayed with a different
            # closure body is fail-closed 409 idempotency_mismatch.
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="idempotency_mismatch",
                message=str(exc),
                correlation_id=correlation_id,
                detail=exc.detail,
            )
        except ConfigError as exc:
            return _backend_requirement_response(
                "closure_unavailable", exc, correlation_id
            )
        except RuntimeError as exc:
            logger.warning("Control-plane closure unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="closure_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        # AG3-138 AC10: rejected closures map to 409 exactly like phase mutations.
        return _mutation_result_response(result, correlation_id=correlation_id)

    def _handle_post_project_edge_sync(
        self,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        try:
            request = ProjectEdgeSyncRequest.model_validate(payload)
            result = self._runtime_service.sync_project_edge(request)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY
                if op_id_validation_error(exc)
                else HTTPStatus.BAD_REQUEST,
                error_code="invalid_project_edge_sync_payload",
                message="Invalid project-edge sync payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except ConfigError as exc:
            return _backend_requirement_response(
                "project_edge_sync_unavailable", exc, correlation_id
            )
        except RuntimeError as exc:
            logger.warning("Project-edge sync unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="project_edge_sync_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_post_command_result(
        self,
        *,
        command_id: str,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        """Handle an Edge command result submission (FK-91 §91.1b, AG3-145)."""
        try:
            request = EdgeCommandResultRequest.model_validate(payload)
            result = self._runtime_service.submit_command_result(command_id, request)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY
                if op_id_validation_error(exc)
                else HTTPStatus.BAD_REQUEST,
                error_code="invalid_edge_command_result_payload",
                message="Invalid edge-command result payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except ConfigError as exc:
            return _backend_requirement_response(
                "edge_command_result_unavailable", exc, correlation_id
            )
        except RuntimeError as exc:
            logger.warning("Edge-command result unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="edge_command_result_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _edge_command_result_response(result, correlation_id=correlation_id)

    def _handle_post_admin_abort(
        self,
        *,
        op_id: str,
        payload: object,
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> HttpResponse:
        """Handle a strategist-only in-flight operation abort.

        An unknown operation maps to 404; a target that is no longer live maps
        to 409. A successful abort carries the audited admin note, while a
        partial-write target enters repair and locks further story mutations.
        With authentication enabled, only an attested strategist session may
        cross this boundary. The audited actor is derived from that session and
        is never trusted from the request body.
        """
        try:
            if auth_result is not None and not auth_result.is_human_bff_session:
                return _error_response(
                    HTTPStatus.FORBIDDEN,
                    error_code="admin_abort_forbidden",
                    message="Administrative abort requires a human BFF session",
                    correlation_id=correlation_id,
                )
            request = AdminAbortRequest.model_validate(payload)
            if auth_result is not None and auth_result.session_id is not None:
                request = request.model_copy(
                    update={
                        "session_id": auth_result.session_id,
                        "principal_type": "human_cli",
                    }
                )
            result = self._runtime_service.admin_abort_inflight_operation(op_id, request)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_admin_abort_payload",
                message="Invalid admin-abort payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except OperationNotFoundError:
            return _error_response(
                HTTPStatus.NOT_FOUND,
                error_code="operation_not_found",
                message=f"Operation {op_id!r} not found",
                correlation_id=correlation_id,
            )
        except OperationNotAbortableError as exc:
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="operation_not_abortable",
                message=str(exc),
                correlation_id=correlation_id,
                detail={"current_status": exc.current_status},
            )
        except ConfigError as exc:
            return _backend_requirement_response(
                "admin_abort_unavailable", exc, correlation_id
            )
        except RuntimeError as exc:
            logger.warning("Admin-abort unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="admin_abort_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )


__all__: list[str] = []
