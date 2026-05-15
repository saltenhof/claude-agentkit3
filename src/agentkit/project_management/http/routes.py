"""Project-management routes for the existing control-plane HTTP dispatcher.

The project-management BC uses the custom ``ControlPlaneApplication`` transport,
not a separate FastAPI app. ``ControlPlaneApplication`` registers this adapter
for the unscoped ``/v1/projects`` surface required by FK-73 and FK-72.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.project_management.errors import (
    ProjectAlreadyArchivedError,
    ProjectImmutableFieldError,
    ProjectRepoStillInUseError,
    ProjectStoryIdPrefixConflictError,
)
from agentkit.project_management.lifecycle import (
    archive_project,
    create_project,
    update_configuration,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.project_management.repository import ProjectRepository

_CORRELATION_HEADER = "X-Correlation-Id"
_PROJECT_DETAIL_PATH = re.compile(r"^/v1/projects/(?P<key>[^/]+)$")
_PROJECT_ARCHIVE_PATH = re.compile(r"^/v1/projects/(?P<key>[^/]+)/archive$")
_PROJECT_CONFIG_PATH = re.compile(
    r"^/v1/projects/(?P<key>[^/]+)/configuration$"
)


@dataclass(frozen=True)
class ProjectRouteResponse:
    """Serializable response produced by the project-management HTTP adapter."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


class ProjectConfigurationPatch(BaseModel):
    """Partial configuration update payload for PATCH /v1/projects/{key}/configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_url: str | None = None
    default_branch: str | None = None
    are_url: str | None = None
    default_worker_count: int | None = Field(default=None, ge=1)
    repositories: list[str] | None = None


class CreateProjectRequest(BaseModel):
    """Request body for creating a project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    name: str
    story_id_prefix: str
    configuration: ProjectConfiguration
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")


class UpdateProjectRequest(BaseModel):
    """Request body for mutable project updates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None = None
    configuration: ProjectConfigurationPatch | None = None
    key: str | None = None
    story_id_prefix: str | None = None
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")


class ArchiveProjectRequest(BaseModel):
    """Request body for archiving a project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")
    archived_at: datetime | None = None


class ProjectManagementRoutes:
    """Route handler for the project-management HTTP surface.

    Args:
        repository: Project persistence port.  Defaults to
            ``StateBackendProjectRepository``.
        repos_in_use_checker: Optional callable that receives
            ``(project_key: str, repos: list[str])`` and returns the subset
            of ``repos`` that are still referenced by an *active* (In Progress)
            story.  Used by the PATCH configuration path to enforce
            ``fail-closed`` when removing repos still in use.  When ``None``
            the check is skipped (safe default for unit tests that do not
            exercise the guard path).
    """

    def __init__(
        self,
        repository: ProjectRepository | None = None,
        repos_in_use_checker: Callable[[str, list[str]], list[str]] | None = None,
    ) -> None:
        if repository is None:
            from agentkit.state_backend.store.project_management_repository import (
                StateBackendProjectRepository,
            )

            repository = StateBackendProjectRepository()
        self._repository = repository
        self._repos_in_use_checker = repos_in_use_checker

    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> ProjectRouteResponse | None:
        """Handle project-management GET routes or return None."""

        if route_path == "/v1/projects":
            include_archived = _parse_bool_query(query, "include_archived")
            projects = self._repository.list(include_archived=include_archived)
            return _json_response(
                HTTPStatus.OK,
                {"projects": [_project_payload(project) for project in projects]},
                correlation_id=correlation_id,
            )

        detail_match = _PROJECT_DETAIL_PATH.match(route_path)
        if detail_match is None:
            return None

        project = self._repository.get(detail_match.group("key"))
        if project is None:
            return _not_found_response(correlation_id)
        return _json_response(
            HTTPStatus.OK,
            {"project": _project_payload(project)},
            correlation_id=correlation_id,
        )

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> ProjectRouteResponse | None:
        """Handle project-management POST routes or return None."""

        if route_path == "/v1/projects":
            return self._handle_create(payload, correlation_id)

        archive_match = _PROJECT_ARCHIVE_PATH.match(route_path)
        if archive_match is None:
            return None
        return self._handle_archive(
            archive_match.group("key"),
            payload,
            correlation_id,
        )

    def handle_patch(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> ProjectRouteResponse | None:
        """Handle project-management PATCH routes or return None.

        Routes handled:
          - ``PATCH /v1/projects/{key}``                 (full project patch)
          - ``PATCH /v1/projects/{key}/configuration``   (configuration-only patch)
        """
        config_match = _PROJECT_CONFIG_PATH.match(route_path)
        if config_match is not None:
            return self._handle_patch_configuration(
                config_match.group("key"),
                payload,
                correlation_id,
            )

        detail_match = _PROJECT_DETAIL_PATH.match(route_path)
        if detail_match is None:
            return None

        try:
            request = UpdateProjectRequest.model_validate(payload)
        except ValidationError as exc:
            return _validation_error_response(
                "invalid_project_update_payload",
                "Invalid project update payload",
                correlation_id,
                exc,
            )

        if request.key is not None or request.story_id_prefix is not None:
            return _conflict_response(
                "immutable_project_field",
                "Project key and story_id_prefix are immutable",
                correlation_id,
            )

        project = self._repository.get(detail_match.group("key"))
        if project is None:
            return _not_found_response(correlation_id)

        configuration_updates: dict[str, object] | None = None
        if request.configuration is not None:
            configuration_updates = request.configuration.model_dump(
                mode="python",
                exclude_unset=True,
                exclude_none=False,
            )
        try:
            # When repositories is being updated, check repos-in-use before saving.
            if configuration_updates and "repositories" in configuration_updates:
                new_repos_raw = configuration_updates["repositories"]
                new_repos = (
                    [str(r) for r in new_repos_raw]
                    if isinstance(new_repos_raw, list)
                    else []
                )
                in_use_check = self._check_repos_removal(
                    project.key,
                    list(project.configuration.repositories),
                    new_repos,
                    correlation_id,
                )
                if in_use_check is not None:
                    return in_use_check

            updated = update_configuration(
                project,
                name=request.name,
                configuration_updates=configuration_updates,
            )
            self._repository.save(updated)
        except (ProjectImmutableFieldError, ProjectStoryIdPrefixConflictError) as exc:
            return _conflict_response(
                "project_update_conflict",
                str(exc),
                correlation_id,
            )
        except ValidationError as exc:
            return _validation_error_response(
                "invalid_project_configuration",
                "Invalid project configuration",
                correlation_id,
                exc,
            )

        return _mutation_response(
            HTTPStatus.OK,
            request.op_id,
            correlation_id,
            updated,
            operation_kind="project_update",
        )

    def _handle_patch_configuration(
        self,
        key: str,
        payload: object,
        correlation_id: str,
    ) -> ProjectRouteResponse:
        """Handle PATCH /v1/projects/{key}/configuration.

        Validates the new ``repositories`` list (if present) against active
        stories before persisting the update.

        Args:
            key: Project key from the URL.
            payload: Raw request body.
            correlation_id: Request correlation ID.

        Returns:
            A ``ProjectRouteResponse``.
        """
        try:
            patch = ProjectConfigurationPatch.model_validate(payload)
        except ValidationError as exc:
            return _validation_error_response(
                "invalid_project_configuration_patch",
                "Invalid project configuration patch",
                correlation_id,
                exc,
            )

        project = self._repository.get(key)
        if project is None:
            return _not_found_response(correlation_id)

        op_id = f"op-{uuid.uuid4().hex}"
        configuration_updates = patch.model_dump(
            mode="python",
            exclude_unset=True,
            exclude_none=False,
        )
        # Remove keys that are None (unset optional fields)
        configuration_updates = {
            k: v for k, v in configuration_updates.items() if v is not None
        }

        # Guard: fail-closed if repos being removed are still in active stories.
        if "repositories" in configuration_updates:
            in_use_check = self._check_repos_removal(
                project.key,
                list(project.configuration.repositories),
                list(configuration_updates["repositories"]),
                correlation_id,
            )
            if in_use_check is not None:
                return in_use_check

        try:
            updated = update_configuration(
                project,
                configuration_updates=configuration_updates or None,
            )
            self._repository.save(updated)
        except (ProjectImmutableFieldError, ProjectStoryIdPrefixConflictError) as exc:
            return _conflict_response(
                "project_update_conflict",
                str(exc),
                correlation_id,
            )
        except ValidationError as exc:
            return _validation_error_response(
                "invalid_project_configuration",
                "Invalid project configuration",
                correlation_id,
                exc,
            )
        except ProjectRepoStillInUseError as exc:
            return _validation_error_response_plain(
                "validation_failed",
                str(exc),
                correlation_id,
                detail={"repos_still_in_use": []},
            )

        return _mutation_response(
            HTTPStatus.OK,
            op_id,
            correlation_id,
            updated,
            operation_kind="project_configuration_update",
        )

    def _check_repos_removal(
        self,
        project_key: str,
        current_repos: list[str],
        new_repos: list[str],
        correlation_id: str,
    ) -> ProjectRouteResponse | None:
        """Check whether any repo being removed is still in use by an active story.

        Returns a ``validation_failed`` response when the check finds conflicts,
        or ``None`` when the update is safe to proceed.

        Args:
            project_key: Project key for the in-use lookup.
            current_repos: Current repositories list on the project.
            new_repos: Proposed new repositories list.
            correlation_id: Request correlation ID.

        Returns:
            A ``ProjectRouteResponse`` with ``validation_failed`` if any
            removed repo is still in use by an active story, otherwise ``None``.
        """
        if self._repos_in_use_checker is None:
            return None

        removed = [r for r in current_repos if r not in set(new_repos)]
        if not removed:
            return None

        in_use = self._repos_in_use_checker(project_key, removed)
        if not in_use:
            return None

        return _validation_error_response_plain(
            "validation_failed",
            "Cannot remove repos that are still referenced by active stories",
            correlation_id,
            detail={"repos_still_in_use": in_use},
        )

    def _handle_create(
        self,
        payload: object,
        correlation_id: str,
    ) -> ProjectRouteResponse:
        try:
            request = CreateProjectRequest.model_validate(payload)
        except ValidationError as exc:
            return _validation_error_response(
                "invalid_project_create_payload",
                "Invalid project create payload",
                correlation_id,
                exc,
            )

        if self._repository.get(request.key) is not None:
            return _conflict_response(
                "project_key_conflict",
                "Project key already exists",
                correlation_id,
            )

        project = create_project(
            request.key,
            request.name,
            request.story_id_prefix,
            request.configuration,
        )
        try:
            self._repository.save(project)
        except ProjectStoryIdPrefixConflictError as exc:
            return _conflict_response(
                "project_story_id_prefix_conflict",
                str(exc),
                correlation_id,
            )

        return _mutation_response(
            HTTPStatus.CREATED,
            request.op_id,
            correlation_id,
            project,
            operation_kind="project_create",
        )

    def _handle_archive(
        self,
        key: str,
        payload: object,
        correlation_id: str,
    ) -> ProjectRouteResponse:
        try:
            request = ArchiveProjectRequest.model_validate(payload)
        except ValidationError as exc:
            return _validation_error_response(
                "invalid_project_archive_payload",
                "Invalid project archive payload",
                correlation_id,
                exc,
            )

        project = self._repository.get(key)
        if project is None:
            return _not_found_response(correlation_id)

        try:
            archived = archive_project(
                project,
                archived_at=request.archived_at or datetime.now(UTC),
            )
            self._repository.save(archived)
        except ProjectAlreadyArchivedError as exc:
            return _conflict_response(
                "project_already_archived",
                str(exc),
                correlation_id,
            )

        return _mutation_response(
            HTTPStatus.OK,
            request.op_id,
            correlation_id,
            archived,
            operation_kind="project_archive",
        )


def _parse_bool_query(query: dict[str, list[str]], key: str) -> bool:
    values = query.get(key)
    if not values:
        return False
    return values[0].strip().lower() in {"1", "true", "yes", "on"}


def _project_payload(project: Project) -> dict[str, object]:
    return project.model_dump(mode="json")


def _mutation_response(
    status: HTTPStatus,
    op_id: str,
    correlation_id: str,
    project: Project,
    *,
    operation_kind: str,
) -> ProjectRouteResponse:
    return _json_response(
        status,
        {
            "status": "committed",
            "op_id": op_id,
            "operation_kind": operation_kind,
            "correlation_id": correlation_id,
            "project": _project_payload(project),
        },
        correlation_id=correlation_id,
    )


def _json_response(
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    correlation_id: str,
) -> ProjectRouteResponse:
    return ProjectRouteResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),),
    )


def _error_response(
    status: HTTPStatus,
    *,
    error_code: str,
    message: str,
    correlation_id: str,
    detail: object | None = None,
) -> ProjectRouteResponse:
    payload: dict[str, object] = {
        "error_code": error_code,
        "error": message,
        "correlation_id": correlation_id,
    }
    if detail is not None:
        payload["detail"] = detail
    return _json_response(status, payload, correlation_id=correlation_id)


def _validation_error_response(
    error_code: str,
    message: str,
    correlation_id: str,
    exc: ValidationError,
) -> ProjectRouteResponse:
    return _error_response(
        HTTPStatus.BAD_REQUEST,
        error_code=error_code,
        message=message,
        correlation_id=correlation_id,
        detail=exc.errors(),
    )


def _validation_error_response_plain(
    error_code: str,
    message: str,
    correlation_id: str,
    detail: object | None = None,
) -> ProjectRouteResponse:
    """Return a 400 validation_failed response with a plain (non-Pydantic) detail."""
    return _error_response(
        HTTPStatus.BAD_REQUEST,
        error_code=error_code,
        message=message,
        correlation_id=correlation_id,
        detail=detail,
    )


def _not_found_response(correlation_id: str) -> ProjectRouteResponse:
    return _error_response(
        HTTPStatus.NOT_FOUND,
        error_code="project_not_found",
        message="Project not found",
        correlation_id=correlation_id,
    )


def _conflict_response(
    error_code: str,
    message: str,
    correlation_id: str,
) -> ProjectRouteResponse:
    return _error_response(
        HTTPStatus.CONFLICT,
        error_code=error_code,
        message=message,
        correlation_id=correlation_id,
    )
