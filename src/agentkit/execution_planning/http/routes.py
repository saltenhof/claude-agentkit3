"""Project-scoped execution-planning routes for the control-plane dispatcher."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentkit.execution_planning.entities import (
    ParallelizationConfig,
    StoryDependencyKind,
)
from agentkit.execution_planning.errors import (
    StoryDependencyConflictError,
    StoryDependencyCycleError,
    StoryDependencyNotFoundError,
)
from agentkit.execution_planning.lifecycle import (
    add_dependency,
    assess_readiness,
    remove_dependency,
)

if TYPE_CHECKING:
    from agentkit.execution_planning.lifecycle import PlanningStoryRepository
    from agentkit.execution_planning.repository import (
        ParallelizationConfigRepository,
        StoryDependencyRepository,
    )
    from agentkit.project_management.repository import ProjectRepository

_CORRELATION_HEADER = "X-Correlation-Id"
_DEPENDENCY_GRAPH_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/planning/dependency-graph$",
)
_DEPENDENCIES_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/planning/dependencies$",
)
_DEPENDENCY_DETAIL_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/planning/dependencies/"
    r"(?P<story_id>[^/]+)/(?P<depends_on_story_id>[^/]+)/(?P<kind>[^/]+)$",
)
_NEXT_READY_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/planning/next-ready$",
)
_CONFIG_PATH = re.compile(r"^/v1/projects/(?P<project_key>[^/]+)/planning/config$")


@dataclass(frozen=True)
class ExecutionPlanningRouteResponse:
    """Serializable response produced by execution-planning routes."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


class CreateDependencyRequest(BaseModel):
    """Request body for creating a story dependency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    depends_on_story_id: str
    kind: StoryDependencyKind
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")


class UpsertParallelizationConfigRequest(BaseModel):
    """Request body for writing planning configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_parallel_stories: int = Field(ge=1)
    max_parallel_stories_per_repo: int | None = Field(default=None, ge=1)
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")


class ExecutionPlanningRoutes:
    """Route handler for the execution-planning HTTP surface."""

    def __init__(
        self,
        *,
        project_repository: ProjectRepository | None = None,
        story_repository: PlanningStoryRepository | None = None,
        dependency_repository: StoryDependencyRepository | None = None,
        config_repository: ParallelizationConfigRepository | None = None,
    ) -> None:
        if project_repository is None:
            from agentkit.state_backend.store.project_management_repository import (
                StateBackendProjectRepository,
            )

            project_repository = StateBackendProjectRepository()
        if story_repository is None:
            from agentkit.state_backend.store.planning_story_repository import (
                StateBackendPlanningStoryRepository,
            )

            story_repository = StateBackendPlanningStoryRepository()
        if dependency_repository is None:
            from agentkit.state_backend.store.story_dependency_repository import (
                StateBackendStoryDependencyRepository,
            )

            dependency_repository = StateBackendStoryDependencyRepository()
        if config_repository is None:
            from agentkit.state_backend.store.parallelization_config_repository import (
                StateBackendParallelizationConfigRepository,
            )

            config_repository = StateBackendParallelizationConfigRepository()
        self._project_repository = project_repository
        self._story_repository = story_repository
        self._dependency_repository = dependency_repository
        self._config_repository = config_repository

    def handle_get(
        self,
        route_path: str,
        correlation_id: str,
    ) -> ExecutionPlanningRouteResponse | None:
        """Handle execution-planning GET routes or return None."""

        graph_match = _DEPENDENCY_GRAPH_PATH.match(route_path)
        if graph_match is not None:
            project_key = graph_match.group("project_key")
            if self._project_repository.get(project_key) is None:
                return _not_found_response(correlation_id)
            edges = self._dependency_repository.list_for_project(project_key)
            return _json_response(
                HTTPStatus.OK,
                {"dependencies": [edge.model_dump(mode="json") for edge in edges]},
                correlation_id=correlation_id,
            )

        next_ready_match = _NEXT_READY_PATH.match(route_path)
        if next_ready_match is not None:
            return self._handle_next_ready(
                next_ready_match.group("project_key"),
                correlation_id,
            )

        config_match = _CONFIG_PATH.match(route_path)
        if config_match is not None:
            return self._handle_get_config(
                config_match.group("project_key"),
                correlation_id,
            )
        return None

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> ExecutionPlanningRouteResponse | None:
        """Handle execution-planning POST routes or return None."""

        match = _DEPENDENCIES_PATH.match(route_path)
        if match is None:
            return None
        return self._handle_create_dependency(
            match.group("project_key"),
            payload,
            correlation_id,
        )

    def handle_put(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> ExecutionPlanningRouteResponse | None:
        """Handle execution-planning PUT routes or return None."""

        match = _CONFIG_PATH.match(route_path)
        if match is None:
            return None
        return self._handle_put_config(match.group("project_key"), payload, correlation_id)

    def handle_delete(
        self,
        route_path: str,
        correlation_id: str,
    ) -> ExecutionPlanningRouteResponse | None:
        """Handle execution-planning DELETE routes or return None."""

        match = _DEPENDENCY_DETAIL_PATH.match(route_path)
        if match is None:
            return None
        project_key = match.group("project_key")
        project = self._project_repository.get(project_key)
        if project is None:
            return _not_found_response(correlation_id)
        if project.archived_at is not None:
            return _conflict_response(
                "project_archived",
                "Project is archived",
                correlation_id,
            )
        try:
            remove_dependency(
                story_id=match.group("story_id"),
                depends_on_story_id=match.group("depends_on_story_id"),
                kind=StoryDependencyKind(match.group("kind")),
                dep_repo=self._dependency_repository,
            )
        except ValueError:
            return _validation_error_payload(
                "invalid_dependency_kind",
                "Invalid dependency kind",
                correlation_id,
            )
        except StoryDependencyNotFoundError:
            return _dependency_not_found_response(correlation_id)
        return _json_response(
            HTTPStatus.OK,
            {
                "status": "committed",
                "operation_kind": "story_dependency_remove",
                "correlation_id": correlation_id,
            },
            correlation_id=correlation_id,
        )

    def _handle_create_dependency(
        self,
        project_key: str,
        payload: object,
        correlation_id: str,
    ) -> ExecutionPlanningRouteResponse:
        try:
            request = CreateDependencyRequest.model_validate(payload)
        except ValidationError as exc:
            return _validation_error_response(
                "invalid_dependency_create_payload",
                "Invalid dependency create payload",
                correlation_id,
                exc,
            )
        project = self._project_repository.get(project_key)
        if project is None:
            return _not_found_response(correlation_id)
        if project.archived_at is not None:
            return _conflict_response("project_archived", "Project is archived", correlation_id)
        try:
            edge = add_dependency(
                story_id=request.story_id,
                depends_on_story_id=request.depends_on_story_id,
                kind=request.kind,
                project_key=project_key,
                story_repo=self._story_repository,
                dep_repo=self._dependency_repository,
            )
        except StoryDependencyCycleError as exc:
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="story_dependency_cycle",
                message="Story dependency would create a cycle",
                correlation_id=correlation_id,
                detail={"path": exc.path},
            )
        except StoryDependencyConflictError as exc:
            return _conflict_response("story_dependency_conflict", str(exc), correlation_id)
        except StoryDependencyNotFoundError:
            return _dependency_not_found_response(correlation_id)
        return _json_response(
            HTTPStatus.CREATED,
            {
                "status": "committed",
                "op_id": request.op_id,
                "operation_kind": "story_dependency_add",
                "correlation_id": correlation_id,
                "dependency": edge.model_dump(mode="json"),
            },
            correlation_id=correlation_id,
        )

    def _handle_next_ready(
        self,
        project_key: str,
        correlation_id: str,
    ) -> ExecutionPlanningRouteResponse:
        if self._project_repository.get(project_key) is None:
            return _not_found_response(correlation_id)
        result = assess_readiness(
            project_key=project_key,
            story_repo=self._story_repository,
            dep_repo=self._dependency_repository,
            config_repo=self._config_repository,
        )
        return _json_response(
            HTTPStatus.OK,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_get_config(
        self,
        project_key: str,
        correlation_id: str,
    ) -> ExecutionPlanningRouteResponse:
        if self._project_repository.get(project_key) is None:
            return _not_found_response(correlation_id)
        config = self._config_repository.get(project_key) or ParallelizationConfig(
            project_key=project_key,
            max_parallel_stories=1,
        )
        return _json_response(
            HTTPStatus.OK,
            {"config": config.model_dump(mode="json")},
            correlation_id=correlation_id,
        )

    def _handle_put_config(
        self,
        project_key: str,
        payload: object,
        correlation_id: str,
    ) -> ExecutionPlanningRouteResponse:
        try:
            request = UpsertParallelizationConfigRequest.model_validate(payload)
        except ValidationError as exc:
            return _validation_error_response(
                "invalid_planning_config_payload",
                "Invalid planning config payload",
                correlation_id,
                exc,
            )
        project = self._project_repository.get(project_key)
        if project is None:
            return _not_found_response(correlation_id)
        if project.archived_at is not None:
            return _conflict_response("project_archived", "Project is archived", correlation_id)
        config = ParallelizationConfig(
            project_key=project_key,
            max_parallel_stories=request.max_parallel_stories,
            max_parallel_stories_per_repo=request.max_parallel_stories_per_repo,
        )
        self._config_repository.upsert(config)
        return _json_response(
            HTTPStatus.OK,
            {
                "status": "committed",
                "op_id": request.op_id,
                "operation_kind": "planning_config_upsert",
                "correlation_id": correlation_id,
                "config": config.model_dump(mode="json"),
            },
            correlation_id=correlation_id,
        )


def _json_response(
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    correlation_id: str,
) -> ExecutionPlanningRouteResponse:
    return ExecutionPlanningRouteResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),),
    )


def _validation_error_response(
    error_code: str,
    message: str,
    correlation_id: str,
    exc: ValidationError,
) -> ExecutionPlanningRouteResponse:
    return _error_response(
        HTTPStatus.BAD_REQUEST,
        error_code=error_code,
        message=message,
        correlation_id=correlation_id,
        detail=exc.errors(),
    )


def _validation_error_payload(
    error_code: str,
    message: str,
    correlation_id: str,
) -> ExecutionPlanningRouteResponse:
    return _error_response(
        HTTPStatus.BAD_REQUEST,
        error_code=error_code,
        message=message,
        correlation_id=correlation_id,
    )


def _not_found_response(correlation_id: str) -> ExecutionPlanningRouteResponse:
    return _error_response(
        HTTPStatus.NOT_FOUND,
        error_code="project_not_found",
        message="Project not found",
        correlation_id=correlation_id,
    )


def _dependency_not_found_response(
    correlation_id: str,
) -> ExecutionPlanningRouteResponse:
    return _error_response(
        HTTPStatus.NOT_FOUND,
        error_code="story_dependency_not_found",
        message="Story dependency endpoint not found",
        correlation_id=correlation_id,
    )


def _conflict_response(
    error_code: str,
    message: str,
    correlation_id: str,
) -> ExecutionPlanningRouteResponse:
    return _error_response(
        HTTPStatus.CONFLICT,
        error_code=error_code,
        message=message,
        correlation_id=correlation_id,
    )


def _error_response(
    status: HTTPStatus,
    *,
    error_code: str,
    message: str,
    correlation_id: str,
    detail: object | None = None,
) -> ExecutionPlanningRouteResponse:
    payload: dict[str, object] = {
        "error_code": error_code,
        "error": message,
        "correlation_id": correlation_id,
    }
    if detail is not None:
        payload["detail"] = detail
    return _json_response(status, payload, correlation_id=correlation_id)
