"""Writer-owned HTTP routes for installer control-plane state."""

from __future__ import annotations

import re
import urllib.parse
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ValidationError

from agentkit.backend.control_plane.models import op_id_validation_error
from agentkit.backend.control_plane_http.responses import (
    HttpResponse,
    _error_response,
    _json_response,
)
from agentkit.backend.installer.http_models import (
    GovernanceHookClearRequest,
    GovernanceHookListResponse,
    GovernanceHookRegistrationRequest,
    GovernanceHookRegistrationResponse,
    InstallerWriterReadyResponse,
    ProjectRegistrationListResponse,
    ProjectRegistrationMutationResponse,
    ProjectRegistrationReadResponse,
    ProjectRegistrationUpgradeRequest,
    RegisterProjectStateRequest,
    SkillBindingDeleteRequest,
    SkillBindingListResponse,
    SkillBindingMutationResponse,
    SkillBindingReadResponse,
    SkillBindingWriteRequest,
)
from agentkit.backend.installer.registration import CheckpointStatus
from agentkit.backend.installer.writer_service import InstallerMigrationWitnessError

if TYPE_CHECKING:
    from agentkit.backend.auth.middleware import AuthResult
    from agentkit.backend.installer.mutation_idempotency import (
        InstallerMutationCoordinator,
    )
    from agentkit.backend.installer.writer_service import InstallerWriterService

_BASE = r"^/v1/projects/(?P<project_key>[^/]+)/installation"
_WRITER_READY = re.compile(_BASE + r"/writer-ready$")
_REGISTER_PROJECT = re.compile(_BASE + r"/register-project$")
_PROJECT_REGISTRATION = re.compile(_BASE + r"/project-registration$")
_PROJECT_REGISTRATIONS = re.compile(_BASE + r"/project-registrations$")
_SKILL_BINDINGS = re.compile(_BASE + r"/skill-bindings$")
_SKILL_BINDING = re.compile(_BASE + r"/skill-bindings/(?P<skill_name>[^/]+)$")
_SKILL_BINDING_DELETE = re.compile(
    _BASE + r"/skill-bindings/(?P<skill_name>[^/]+)/delete$",
)
_GOVERNANCE_HOOKS = re.compile(_BASE + r"/governance-hooks$")
_GOVERNANCE_HOOKS_CLEAR = re.compile(_BASE + r"/governance-hooks/clear$")


class _RouteRequest(BaseModel):
    op_id: str


#: Request model per writer mutation. The concrete models are structural, not
#: nominal, subtypes of :class:`_RouteRequest`; the single ``cast`` in
#: :meth:`InstallerWriterRoutes._validate_request` states that once instead of
#: repeating the same annotation string per branch.
_REQUEST_MODELS: dict[str, type[BaseModel]] = {
    "register_project": RegisterProjectStateRequest,
    "project_registration_upgraded": ProjectRegistrationUpgradeRequest,
    "skill_binding_save": SkillBindingWriteRequest,
    "skill_binding_delete": SkillBindingDeleteRequest,
    "governance_hooks_register": GovernanceHookRegistrationRequest,
}


class InstallerWriterRoutes:
    """Execute installer state reads/writes only inside the active writer."""

    def __init__(
        self,
        *,
        owner: InstallerWriterService,
        mutation_coordinator: InstallerMutationCoordinator,
    ) -> None:
        self._owner = owner
        self._mutation_coordinator = mutation_coordinator

    def handle_get(
        self,
        route_path: str,
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> HttpResponse | None:
        """Dispatch authenticated installer state reads and readiness proof."""

        match = self._match_get(route_path)
        if match is None:
            return None
        operation, project_key, target = match
        forbidden = self._require_project_token(
            project_key,
            auth_result,
            correlation_id,
        )
        if forbidden is not None:
            return forbidden
        if operation == "writer_ready":
            return _json_response(
                HTTPStatus.OK,
                InstallerWriterReadyResponse(ready=True).model_dump(mode="json"),
                correlation_id=correlation_id,
            )
        try:
            return self._execute_get(
                operation,
                project_key,
                target,
                correlation_id,
            )
        except (OSError, RuntimeError) as exc:
            return self._unavailable(exc, correlation_id)

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> HttpResponse | None:
        """Dispatch one authenticated, replayable installer state mutation."""

        match = self._match_post(route_path)
        if match is None:
            return None
        operation, project_key, target = match
        forbidden = self._require_project_token(
            project_key,
            auth_result,
            correlation_id,
        )
        if forbidden is not None:
            return forbidden
        try:
            request = self._validate_request(operation, payload)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY
                if op_id_validation_error(exc)
                else HTTPStatus.BAD_REQUEST,
                error_code="invalid_installer_writer_request",
                message="Invalid installer writer request",
                correlation_id=correlation_id,
                detail=str(exc),
            )
        session_id = cast("str", cast("AuthResult", auth_result).token_id)
        identity_body = request.model_dump(mode="json")
        identity_body["project_key"] = project_key
        if target is not None:
            identity_body["target"] = target
        try:
            return self._mutation_coordinator.run(
                operation=operation,
                op_id=request.op_id,
                project_key=project_key,
                request_body=identity_body,
                session_id=session_id,
                correlation_id=correlation_id,
                mutate=lambda: self._execute_post(
                    operation,
                    project_key,
                    target,
                    request,
                    correlation_id,
                ),
                replay=lambda stored: self._replay_response(stored, correlation_id),
                conflict=lambda code, message, detail: _error_response(
                    HTTPStatus.CONFLICT,
                    error_code=code,
                    message=message,
                    correlation_id=correlation_id,
                    detail=detail,
                ),
            )
        except InstallerMigrationWitnessError as exc:
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code="invalid_config_migration_witness",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except (OSError, RuntimeError) as exc:
            return self._unavailable(exc, correlation_id)

    def _execute_get(
        self,
        operation: str,
        project_key: str,
        target: str | None,
        correlation_id: str,
    ) -> HttpResponse:
        payload: BaseModel
        if operation == "project_registration":
            registration = self._owner.get_project_registration(project_key)
            payload = ProjectRegistrationReadResponse(
                registration=(
                    None
                    if registration is None
                    else registration.model_dump(mode="json")
                ),
            )
        elif operation == "project_registrations":
            registration = self._owner.get_project_registration(project_key)
            payload = ProjectRegistrationListResponse(
                registrations=(
                    ()
                    if registration is None
                    else (registration.model_dump(mode="json"),)
                ),
            )
        elif operation == "skill_binding":
            binding = self._owner.get_skill_binding(project_key, str(target))
            payload = SkillBindingReadResponse(
                binding=None if binding is None else binding.model_dump(mode="json"),
            )
        elif operation == "skill_bindings":
            payload = SkillBindingListResponse(
                bindings=tuple(
                    binding.model_dump(mode="json")
                    for binding in self._owner.list_skill_bindings(project_key)
                ),
            )
        else:
            payload = GovernanceHookListResponse(
                hook_definitions=tuple(
                    self._owner.list_governance_hooks(project_key),
                ),
            )
        return _json_response(
            HTTPStatus.OK,
            payload.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _execute_post(
        self,
        operation: str,
        project_key: str,
        target: str | None,
        request: _RouteRequest,
        correlation_id: str,
    ) -> HttpResponse:
        if operation == "register_project":
            checkpoint_result = self._owner.register_project(
                project_key,
                cast("RegisterProjectStateRequest", request),
            )
            body = checkpoint_result.model_dump(mode="json")
            if (
                checkpoint_result.status is CheckpointStatus.FAILED
                and checkpoint_result.reason == "project_management_sync_failed"
            ):
                return _error_response(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    error_code="project_management_sync_failed",
                    message=(
                        checkpoint_result.detail
                        or "CP7 visible project synchronization failed"
                    ),
                    correlation_id=correlation_id,
                    detail=body,
                )
        elif operation == "project_registration_upgraded":
            self._owner.update_project_registration_after_upgrade(
                project_key,
                cast("ProjectRegistrationUpgradeRequest", request),
            )
            body = ProjectRegistrationMutationResponse(
                project_key=project_key,
                action="upgraded",
            ).model_dump(mode="json")
        elif operation == "skill_binding_save":
            write = cast("SkillBindingWriteRequest", request)
            skill_name = str(target)
            if write.skill_name != skill_name:
                return self._target_mismatch(correlation_id)
            self._owner.save_skill_binding(project_key, write)
            body = SkillBindingMutationResponse(
                skill_name=skill_name,
                action="saved",
            ).model_dump(mode="json")
        elif operation == "skill_binding_delete":
            skill_name = str(target)
            self._owner.delete_skill_binding(project_key, skill_name)
            body = SkillBindingMutationResponse(
                skill_name=skill_name,
                action="deleted",
            ).model_dump(mode="json")
        elif operation == "governance_hooks_register":
            hook_request = cast("GovernanceHookRegistrationRequest", request)
            hook_result = self._owner.register_governance_hooks(
                project_key,
                list(hook_request.hook_definitions),
            )
            body = GovernanceHookRegistrationResponse(
                registered=tuple(hook_result.registered),
                skipped=tuple(hook_result.skipped),
                errors=tuple(str(error) for error in hook_result.errors),
            ).model_dump(mode="json")
        else:
            self._owner.clear_governance_hooks(project_key)
            body = {"cleared": True}
        return _json_response(
            HTTPStatus.OK,
            body,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _validate_request(operation: str, payload: object) -> _RouteRequest:
        model = _REQUEST_MODELS.get(operation, GovernanceHookClearRequest)
        return cast("_RouteRequest", model.model_validate(payload))

    @staticmethod
    def _match_get(route_path: str) -> tuple[str, str, str | None] | None:
        for pattern, operation, target_group in (
            (_WRITER_READY, "writer_ready", None),
            (_PROJECT_REGISTRATION, "project_registration", None),
            (_PROJECT_REGISTRATIONS, "project_registrations", None),
            (_SKILL_BINDING, "skill_binding", "skill_name"),
            (_SKILL_BINDINGS, "skill_bindings", None),
            (_GOVERNANCE_HOOKS, "governance_hooks", None),
        ):
            match = pattern.match(route_path)
            if match is not None:
                target = (
                    urllib.parse.unquote(match.group(target_group))
                    if target_group is not None
                    else None
                )
                return (
                    operation,
                    urllib.parse.unquote(match.group("project_key")),
                    target,
                )
        return None

    @staticmethod
    def _match_post(route_path: str) -> tuple[str, str, str | None] | None:
        for pattern, operation, target_group in (
            (_REGISTER_PROJECT, "register_project", None),
            (
                _PROJECT_REGISTRATION,
                "project_registration_upgraded",
                None,
            ),
            (_SKILL_BINDING_DELETE, "skill_binding_delete", "skill_name"),
            (_SKILL_BINDING, "skill_binding_save", "skill_name"),
            (_GOVERNANCE_HOOKS_CLEAR, "governance_hooks_clear", None),
            (_GOVERNANCE_HOOKS, "governance_hooks_register", None),
        ):
            match = pattern.match(route_path)
            if match is not None:
                target = (
                    urllib.parse.unquote(match.group(target_group))
                    if target_group is not None
                    else None
                )
                return (
                    operation,
                    urllib.parse.unquote(match.group("project_key")),
                    target,
                )
        return None

    @staticmethod
    def _require_project_token(
        project_key: str,
        auth_result: AuthResult | None,
        correlation_id: str,
    ) -> HttpResponse | None:
        if (
            auth_result is not None
            and auth_result.auth_kind == "project_api_token"
            and auth_result.project_key == project_key
            and bool(str(auth_result.token_id or "").strip())
        ):
            return None
        return _error_response(
            HTTPStatus.FORBIDDEN,
            error_code="project_token_required",
            message="Installer writer routes require the scoped project token",
            correlation_id=correlation_id,
        )

    @staticmethod
    def _replay_response(
        result_payload: dict[str, object],
        correlation_id: str,
    ) -> HttpResponse:
        status_raw = result_payload.get("status_code")
        body_raw = result_payload.get("body")
        if (
            not isinstance(status_raw, int)
            or status_raw not in HTTPStatus._value2member_map_
            or not isinstance(body_raw, dict)
        ):
            return _error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code="corrupt_idempotency_record",
                message="Stored installer idempotency result is malformed",
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus(status_raw),
            {str(key): value for key, value in body_raw.items()},
            correlation_id=correlation_id,
        )

    @staticmethod
    def _target_mismatch(correlation_id: str) -> HttpResponse:
        return _error_response(
            HTTPStatus.BAD_REQUEST,
            error_code="installer_target_mismatch",
            message="Installer route target does not match the request body",
            correlation_id=correlation_id,
        )

    @staticmethod
    def _unavailable(exc: Exception, correlation_id: str) -> HttpResponse:
        return _error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            error_code="control_plane_writer_unavailable",
            message=str(exc),
            correlation_id=correlation_id,
        )

__all__ = ["InstallerWriterRoutes"]
