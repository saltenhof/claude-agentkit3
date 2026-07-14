"""Thin HTTP routes for backend-owned third-party validation."""

from __future__ import annotations

import re
import urllib.parse
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.control_plane.third_party_models import (
    BranchPluginSelfTestRequest,
    ThirdPartyValidationRequest,
)
from agentkit.backend.control_plane_http.responses import HttpResponse, _error_response, _json_response
from agentkit.backend.installer.third_party_errors import (
    ThirdPartyOperationConflictError,
    ThirdPartyServiceUnavailableError,
)

if TYPE_CHECKING:
    from agentkit.backend.installer.third_party_preflight import ThirdPartyPreflightService

_VALIDATION = re.compile(r"^/v1/projects/(?P<project_key>[^/]+)/installation/third-party-validation$")
_SELF_TEST = re.compile(r"^/v1/projects/(?P<project_key>[^/]+)/installation/branch-plugin-self-test$")
_OPERATION = re.compile(r"^/v1/project-edge/operations/(?P<op_id>[^/]+)$")


class ThirdPartyValidationRoutes:
    """Serialize requests and delegate every decision to the core service."""

    def __init__(self, service: ThirdPartyPreflightService) -> None:
        self._service = service

    def handle_post(self, route_path: str, payload: object, correlation_id: str) -> HttpResponse | None:
        """Handle light validation or explicit self-test submission."""
        validation = _VALIDATION.match(route_path)
        if validation is not None:
            return self._validate(validation.group("project_key"), payload, correlation_id)
        self_test = _SELF_TEST.match(route_path)
        if self_test is None:
            return None
        try:
            request = BranchPluginSelfTestRequest.model_validate(payload)
            result = self._service.start_self_test(
                urllib.parse.unquote(self_test.group("project_key")), request
            )
        except ValidationError as exc:
            return _bad_request("invalid_branch_plugin_self_test_request", exc, correlation_id)
        except ThirdPartyOperationConflictError as exc:
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code=exc.error_code,
                message=str(exc),
                correlation_id=correlation_id,
            )
        except ThirdPartyServiceUnavailableError as exc:
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="third_party_service_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        status = HTTPStatus.ACCEPTED if result.status == "accepted" else HTTPStatus.OK
        return _json_response(status, result.model_dump(mode="json"), correlation_id=correlation_id)

    def handle_get(self, route_path: str, correlation_id: str) -> HttpResponse | None:
        """Poll self-test state through the canonical operation read path."""
        match = _OPERATION.match(route_path)
        if match is None:
            return None
        op_id = urllib.parse.unquote(match.group("op_id"))
        result = self._service.get_self_test_operation(op_id)
        if result is None:
            return None
        return _json_response(HTTPStatus.OK, result.model_dump(mode="json"), correlation_id=correlation_id)

    def _validate(self, project_key: str, payload: object, correlation_id: str) -> HttpResponse:
        try:
            request = ThirdPartyValidationRequest.model_validate(payload)
        except ValidationError as exc:
            return _bad_request("invalid_third_party_validation_request", exc, correlation_id)
        try:
            result = self._service.validate_idempotent(
                urllib.parse.unquote(project_key), request, correlation_id
            )
        except ThirdPartyOperationConflictError as exc:
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code=exc.error_code,
                message=str(exc),
                correlation_id=correlation_id,
            )
        except ThirdPartyServiceUnavailableError as exc:
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="third_party_service_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK, result.model_dump(mode="json"), correlation_id=correlation_id
        )


def _bad_request(code: str, exc: ValidationError, correlation_id: str) -> HttpResponse:
    errors = [
        {"type": error["type"], "loc": error["loc"], "msg": error["msg"]}
        for error in exc.errors()
    ]
    return _error_response(
        HTTPStatus.BAD_REQUEST,
        error_code=code,
        message="Invalid request",
        correlation_id=correlation_id,
        detail={"errors": errors},
    )


__all__ = ["ThirdPartyValidationRoutes"]
