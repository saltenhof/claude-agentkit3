"""Project-scoped story routes for the control-plane dispatcher."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentkit.story.service import StoryService
from agentkit.story_context_manager.errors import (
    StoryIdentityConflictError,
    StoryProjectArchivedError,
    StoryProjectNotFoundError,
)
from agentkit.story_context_manager.lifecycle import create_story
from agentkit.story_context_manager.sizing import StorySize
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)

if TYPE_CHECKING:
    from agentkit.project_management.repository import ProjectRepository
    from agentkit.story_context_manager.repository import StoryContextRepository

_CORRELATION_HEADER = "X-Correlation-Id"
_STORY_COLLECTION_PATH = re.compile(r"^/v1/projects/(?P<project_key>[^/]+)/stories$")
_STORY_DETAIL_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)$",
)


@dataclass(frozen=True)
class StoryRouteResponse:
    """Serializable response produced by the story-context HTTP adapter."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


class CreateStoryRequest(BaseModel):
    """Request body for story creation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_type: StoryType
    execution_route: StoryMode
    implementation_contract: ImplementationContract | None = None
    issue_nr: int | None = None
    title: str = ""
    story_size: StorySize = StorySize.SMALL
    participating_repos: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")


class StoryContextRoutes:
    """Route handler for project-scoped story-context endpoints."""

    def __init__(
        self,
        *,
        project_repository: ProjectRepository | None = None,
        story_repository: StoryContextRepository | None = None,
        story_service: StoryService | None = None,
    ) -> None:
        if project_repository is None:
            from agentkit.state_backend.store.project_management_repository import (
                StateBackendProjectRepository,
            )

            project_repository = StateBackendProjectRepository()
        if story_repository is None:
            from agentkit.state_backend.store.story_context_repository import (
                StateBackendStoryContextRepository,
            )

            story_repository = StateBackendStoryContextRepository()
        self._project_repository = project_repository
        self._story_repository = story_repository
        self._story_service = story_service or StoryService()

    def handle_get(
        self,
        route_path: str,
        correlation_id: str,
    ) -> StoryRouteResponse | None:
        """Handle project-scoped story GET routes or return None."""

        collection_match = _STORY_COLLECTION_PATH.match(route_path)
        if collection_match is not None:
            project_key = collection_match.group("project_key")
            result = self._story_service.list_stories(project_key)
            return _json_response(
                HTTPStatus.OK,
                result.model_dump(mode="json"),
                correlation_id=correlation_id,
            )

        detail_match = _STORY_DETAIL_PATH.match(route_path)
        if detail_match is None:
            return None

        project_key = detail_match.group("project_key")
        story_id = detail_match.group("story_id")
        project = self._project_repository.get(project_key)
        if project is None:
            return _not_found_response(correlation_id)
        if not story_id.startswith(f"{project.story_id_prefix}-"):
            return _not_found_response(correlation_id)

        detail = self._story_service.get_story(project_key, story_id)
        if detail is None:
            return _not_found_response(correlation_id)
        return _json_response(
            HTTPStatus.OK,
            detail.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> StoryRouteResponse | None:
        """Handle project-scoped story POST routes or return None."""

        collection_match = _STORY_COLLECTION_PATH.match(route_path)
        if collection_match is None:
            return None

        try:
            request = CreateStoryRequest.model_validate(payload)
        except ValidationError as exc:
            return _validation_error_response(
                "invalid_story_create_payload",
                "Invalid story create payload",
                correlation_id,
                exc,
            )

        try:
            story = create_story(
                project_key=collection_match.group("project_key"),
                story_type=request.story_type,
                execution_route=request.execution_route,
                implementation_contract=request.implementation_contract,
                issue_nr=request.issue_nr,
                title=request.title,
                story_size=request.story_size,
                participating_repos=request.participating_repos,
                labels=request.labels,
                created_at=datetime.now(UTC),
                project_repository=self._project_repository,
                story_repository=self._story_repository,
            )
        except (StoryProjectNotFoundError, StoryProjectArchivedError) as exc:
            return _conflict_response("story_project_unavailable", str(exc), correlation_id)
        except StoryIdentityConflictError as exc:
            return _conflict_response("story_identity_conflict", str(exc), correlation_id)

        return _json_response(
            HTTPStatus.CREATED,
            {
                "status": "committed",
                "op_id": request.op_id,
                "operation_kind": "story_create",
                "correlation_id": correlation_id,
                "story": story.model_dump(mode="json"),
            },
            correlation_id=correlation_id,
        )


def _json_response(
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    correlation_id: str,
) -> StoryRouteResponse:
    return StoryRouteResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),),
    )


def _validation_error_response(
    error_code: str,
    message: str,
    correlation_id: str,
    exc: ValidationError,
) -> StoryRouteResponse:
    return _error_response(
        HTTPStatus.BAD_REQUEST,
        error_code=error_code,
        message=message,
        correlation_id=correlation_id,
        detail=exc.errors(),
    )


def _not_found_response(correlation_id: str) -> StoryRouteResponse:
    return _error_response(
        HTTPStatus.NOT_FOUND,
        error_code="story_not_found",
        message="Story not found",
        correlation_id=correlation_id,
    )


def _conflict_response(
    error_code: str,
    message: str,
    correlation_id: str,
) -> StoryRouteResponse:
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
) -> StoryRouteResponse:
    payload: dict[str, object] = {
        "error_code": error_code,
        "error": message,
        "correlation_id": correlation_id,
    }
    if detail is not None:
        payload["detail"] = detail
    return _json_response(status, payload, correlation_id=correlation_id)
