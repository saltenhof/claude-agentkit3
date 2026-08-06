"""Writer-owned HTTPS routes for story reset and human exit."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from pydantic import ValidationError

from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
from agentkit.backend.control_plane_http.responses import HttpResponse, _error_response, _json_response
from agentkit.backend.governance.principal_capabilities.principals import Principal
from agentkit.backend.story_exit.http_models import StoryExitMutationRequest, StoryExitMutationResponse
from agentkit.backend.story_exit.models import ExitReason
from agentkit.backend.story_exit.service import StoryExitError, StoryExitRequest, StoryExitResult
from agentkit.backend.story_reset.http_models import StoryResetMutationRequest, StoryResetMutationResponse
from agentkit.backend.story_reset.models import (
    PlannedPurge,
    StoryResetRecord,
    StoryResetRequest,
    StoryResetResult,
)
from agentkit.backend.story_reset.service import StoryResetError

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.auth.middleware import AuthResult


class _ResetServicePort(Protocol):
    def request_reset(
        self, request: StoryResetRequest
    ) -> StoryResetRecord | PlannedPurge: ...
    def execute_reset(self, reset_id: str) -> StoryResetResult: ...


class _ExitServicePort(Protocol):
    def exit_story(self, request: StoryExitRequest) -> StoryExitResult: ...


class StoryAdminRoutes:
    """Authenticate and execute reset/exit inside the lease-owning writer."""

    def __init__(
        self,
        *,
        reset_service_builder: Callable[..., object] | None = None,
        exit_service_builder: Callable[..., object] | None = None,
        repository: ControlPlaneRuntimeRepository | None = None,
    ) -> None:
        self._reset_service_builder = reset_service_builder
        self._exit_service_builder = exit_service_builder
        self._repository = repository or ControlPlaneRuntimeRepository()

    def handle_reset(
        self,
        *,
        project_key: str,
        story_id: str,
        payload: object,
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> HttpResponse:
        """Execute a story reset using only the authenticated strategist identity."""

        forbidden = self._require_strategist(auth_result, correlation_id)
        if forbidden is not None:
            return forbidden
        try:
            wire = StoryResetMutationRequest.model_validate(payload)
            root = Path(wire.project_root)
            service = self._build_reset_service(project_key, root)
            outcome = service.request_reset(
                StoryResetRequest(
                    project_key=project_key,
                    story_id=story_id,
                    requested_by=str(cast("AuthResult", auth_result).session_id),
                    reason=wire.reason,
                    escalation_ref=wire.escalation_ref,
                    dry_run=wire.dry_run,
                    force=wire.force,
                    reset_id=wire.op_id,
                ),
            )
            if isinstance(outcome, PlannedPurge):
                response = StoryResetMutationResponse(
                    mode="dry-run",
                    status="planned",
                    reset_id=wire.op_id,
                    story_id=story_id,
                    run_id=outcome.run_id,
                    planned_domains=tuple(domain.value for domain in outcome.planned_domains),
                )
            else:
                result = service.execute_reset(outcome.reset_id)
                response = StoryResetMutationResponse(
                    mode="execute",
                    status=result.record.status.value,
                    reset_id=result.reset_id,
                    story_id=result.record.story_id,
                    run_id=result.clean_state.run_id,
                    clean_state=result.clean_state.is_clean,
                    purge_summary=result.record.purge_summary,
                    resumed=result.resumed,
                )
        except ValidationError as exc:
            return self._invalid("invalid_story_reset_request", exc, correlation_id)
        except StoryResetError as exc:
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="story_reset_rejected",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except (OSError, RuntimeError) as exc:
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="story_reset_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            response.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def handle_exit(
        self,
        *,
        project_key: str,
        story_id: str,
        payload: object,
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> HttpResponse:
        """Execute a story exit against the writer-resolved active run owner."""

        forbidden = self._require_strategist(auth_result, correlation_id)
        if forbidden is not None:
            return forbidden
        try:
            wire = StoryExitMutationRequest.model_validate(payload)
            active = self._repository.load_active_ownership(project_key, story_id)
            if active is None or active.run_id != wire.run_id:
                raise StoryExitError("story exit requires the active bound run")
            service = self._build_exit_service(project_key)
            result = service.exit_story(
                StoryExitRequest(
                    project_key=project_key,
                    story_id=story_id,
                    run_id=wire.run_id,
                    session_id=active.owner_session_id,
                    reason=ExitReason(wire.reason),
                    note=wire.note,
                    principal=Principal.HUMAN_CLI,
                    exit_id=wire.op_id,
                ),
            )
        except ValidationError as exc:
            return self._invalid("invalid_story_exit_request", exc, correlation_id)
        except ValueError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_story_exit_reason",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except StoryExitError as exc:
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="story_exit_rejected",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except (OSError, RuntimeError) as exc:
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="story_exit_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        response = StoryExitMutationResponse(
            status="committed",
            exit_id=result.exit_id,
            story_id=result.record.story_id,
            operating_mode=result.operating_mode,
            artifact_dir=str(result.artifact_dir),
        )
        return _json_response(
            HTTPStatus.OK,
            response.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    @staticmethod
    def _require_strategist(
        auth_result: AuthResult | None,
        correlation_id: str,
    ) -> HttpResponse | None:
        if (
            auth_result is not None
            and auth_result.is_human_bff_session
            and bool(str(auth_result.session_id or "").strip())
        ):
            return None
        return _error_response(
            HTTPStatus.FORBIDDEN,
            error_code="story_admin_forbidden",
            message="Story administration requires a strategist session",
            correlation_id=correlation_id,
        )

    @staticmethod
    def _invalid(code: str, exc: ValidationError, correlation_id: str) -> HttpResponse:
        return _error_response(
            HTTPStatus.BAD_REQUEST,
            error_code=code,
            message="Invalid story-administration request",
            correlation_id=correlation_id,
            detail=str(exc),
        )

    def _build_reset_service(self, project_key: str, root: Path) -> _ResetServicePort:
        builder = self._reset_service_builder
        if builder is None:
            from agentkit.backend.bootstrap.composition_root import build_story_reset_service

            builder = build_story_reset_service
        service = builder(project_key=project_key, store_dir=root, project_root=root)
        return cast("_ResetServicePort", service)

    def _build_exit_service(self, project_key: str) -> _ExitServicePort:
        builder = self._exit_service_builder
        if builder is None:
            from agentkit.backend.bootstrap.composition_root import build_story_exit_service

            builder = build_story_exit_service
        return cast("_ExitServicePort", builder(project_key=project_key))


__all__ = ["StoryAdminRoutes"]
