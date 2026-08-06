"""Writer-owned HTTP route for the administrative story-split saga."""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from pydantic import ValidationError

from agentkit.backend.control_plane_http.responses import HttpResponse, _error_response, _json_response
from agentkit.backend.governance.principal_capabilities.principals import Principal
from agentkit.backend.story_split.http_models import (
    StorySplitMutationRequest,
    StorySplitMutationResponse,
)
from agentkit.backend.story_split.models import SplitPlan
from agentkit.backend.story_split.service import StorySplitError, StorySplitRequest, StorySplitResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.auth.middleware import AuthResult


class _StorySplitServicePort(Protocol):
    def split_story(self, request: StorySplitRequest) -> StorySplitResult:
        """Execute one validated story split."""


class StorySplitRoutes:
    """Authenticate, validate, and dispatch a split inside the active writer."""

    def __init__(
        self,
        service_builder: Callable[..., object] | None = None,
    ) -> None:
        self._service_builder = service_builder

    def handle_post(
        self,
        *,
        project_key: str,
        story_id: str,
        payload: object,
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> HttpResponse:
        """Execute the project-scoped split through the lease-owning process."""
        if auth_result is None or not auth_result.is_human_bff_session:
            return _error_response(
                HTTPStatus.FORBIDDEN,
                error_code="story_split_forbidden",
                message="Administrative story split requires a strategist session",
                correlation_id=correlation_id,
            )
        try:
            wire_request = StorySplitMutationRequest.model_validate(payload)
            raw_plan = json.loads(wire_request.plan_text)
            plan = SplitPlan.model_validate(raw_plan)
        except (ValidationError, json.JSONDecodeError) as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_story_split_request",
                message="Invalid story-split request",
                correlation_id=correlation_id,
                detail=str(exc),
            )
        if plan.project_key != project_key or plan.source_story_id != story_id:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="story_split_scope_mismatch",
                message="Split plan does not match the project-scoped route",
                correlation_id=correlation_id,
            )
        try:
            service = self._build_service(
                project_key=project_key,
                project_root=wire_request.project_root,
            )
            result = service.split_story(
                StorySplitRequest(
                    project_key=project_key,
                    source_story_id=story_id,
                    plan=plan,
                    plan_text=wire_request.plan_text,
                    reason=wire_request.reason,
                    requested_by=auth_result.session_id or "strategist_session",
                    run_id=wire_request.run_id,
                    principal=Principal.HUMAN_CLI,
                ),
            )
        except StorySplitError as exc:
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="story_split_rejected",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except (OSError, RuntimeError) as exc:
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="story_split_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        response = StorySplitMutationResponse(
            status=result.record.status.value,
            split_id=result.split_id,
            source_story_id=result.record.source_story_id,
            successor_ids=result.successor_ids,
            resumed=result.resumed,
        )
        return _json_response(
            HTTPStatus.OK,
            response.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _build_service(
        self,
        *,
        project_key: str,
        project_root: str,
    ) -> _StorySplitServicePort:
        builder = self._service_builder
        if builder is None:
            from agentkit.backend.bootstrap.composition_root import build_story_split_service

            builder = build_story_split_service
        root = Path(project_root)
        service = builder(
            project_key=project_key,
            stories_root=root / "stories",
            project_root=str(root),
        )
        if not hasattr(service, "split_story"):
            raise RuntimeError("story-split composition returned an invalid service")
        return cast("_StorySplitServicePort", service)


__all__ = ["StorySplitRoutes"]
