"""Writer-owned HTTPS routes for failure-corpus mutations."""

from __future__ import annotations

import re
from http import HTTPStatus
from typing import TYPE_CHECKING, Protocol, cast

from pydantic import ValidationError

from agentkit.backend.control_plane.models import op_id_validation_error
from agentkit.backend.control_plane_http.responses import HttpResponse, _error_response, _json_response
from agentkit.backend.failure_corpus.errors import FailureCorpusError
from agentkit.backend.failure_corpus.http_models import (
    FailureCorpusCheckReviewRequest,
    FailureCorpusCheckReviewResponse,
    FailureCorpusEffectivenessRequest,
    FailureCorpusEffectivenessResponse,
    FailureCorpusIncidentMutationRequest,
    FailureCorpusIncidentMutationResponse,
    FailureCorpusPatternReviewRequest,
    FailureCorpusPatternReviewResponse,
)
from agentkit.backend.failure_corpus.incident import IncidentCandidate
from agentkit.backend.failure_corpus.mutation_idempotency import (
    FailureCorpusMutationCoordinator,
)
from agentkit.backend.failure_corpus.types import CheckId, IncidentId, PatternId

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.auth.middleware import AuthResult
    from agentkit.backend.failure_corpus.top import (
        CheckProposal,
        EffectivenessReport,
        FailurePattern,
    )

_INCIDENTS = re.compile(r"^/v1/projects/(?P<project_key>[^/]+)/failure-corpus/incidents$")
_PATTERN_REVIEW = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/failure-corpus/"
    r"patterns/(?P<pattern_id>[^/]+)/review$",
)
_CHECK_REVIEW = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/failure-corpus/"
    r"checks/(?P<check_id>[^/]+)/review$",
)
_EFFECTIVENESS = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/failure-corpus/effectiveness-report$",
)

_FailureCorpusMutationRequest = (
    FailureCorpusIncidentMutationRequest
    | FailureCorpusPatternReviewRequest
    | FailureCorpusCheckReviewRequest
    | FailureCorpusEffectivenessRequest
)


class _FailureCorpusPort(Protocol):
    def record_incident(self, candidate: IncidentCandidate) -> IncidentId: ...

    def confirm_pattern(self, pattern_id: PatternId, decision: object, **kwargs: object) -> FailurePattern: ...

    def approve_check(self, check_id: CheckId, decision: object, **kwargs: object) -> CheckProposal: ...

    def report_effectiveness(self, window_days: int = 90) -> EffectivenessReport: ...


class FailureCorpusRoutes:
    """Authenticate and execute failure-corpus mutations inside the writer."""

    def __init__(
        self,
        *,
        corpus_builder: Callable[[str], object] | None = None,
        mutation_coordinator: FailureCorpusMutationCoordinator | None = None,
    ) -> None:
        self._corpus_builder = corpus_builder
        self._mutation_coordinator = mutation_coordinator

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> HttpResponse | None:
        """Dispatch one project-scoped failure-corpus mutation."""

        matched = self._match(route_path)
        if matched is None:
            return None
        forbidden = self._require_strategist(auth_result, correlation_id)
        if forbidden is not None:
            return forbidden
        operation, project_key, target_id = matched
        try:
            wire_request = self._validate_request(operation, payload)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY
                if op_id_validation_error(exc)
                else HTTPStatus.BAD_REQUEST,
                error_code="invalid_failure_corpus_request",
                message="Invalid failure-corpus mutation request",
                correlation_id=correlation_id,
                detail=str(exc),
            )
        try:
            coordinator = (
                self._mutation_coordinator or FailureCorpusMutationCoordinator()
            )
            return coordinator.run(
                operation=operation,
                op_id=wire_request.op_id,
                project_key=project_key,
                target_id=target_id,
                request_body=wire_request.model_dump(mode="json"),
                session_id=str(cast("AuthResult", auth_result).session_id),
                correlation_id=correlation_id,
                mutate=lambda: self._mutate(
                    operation=operation,
                    project_key=project_key,
                    target_id=target_id,
                    wire_request=wire_request,
                    correlation_id=correlation_id,
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
        except (OSError, RuntimeError) as exc:
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="failure_corpus_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )

    def _mutate(
        self,
        *,
        operation: str,
        project_key: str,
        target_id: str | None,
        wire_request: _FailureCorpusMutationRequest,
        correlation_id: str,
    ) -> HttpResponse:
        """Execute and map one freshly claimed domain mutation."""

        try:
            corpus = self._build_corpus(project_key)
            response = self._execute(
                corpus,
                operation,
                project_key,
                target_id,
                wire_request,
            )
        except (FailureCorpusError, ValueError) as exc:
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="failure_corpus_mutation_rejected",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except (OSError, RuntimeError) as exc:
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="failure_corpus_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            response.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    @staticmethod
    def _match(route_path: str) -> tuple[str, str, str | None] | None:
        for pattern, operation, group in (
            (_INCIDENTS, "add_incident", None),
            (_PATTERN_REVIEW, "review_pattern", "pattern_id"),
            (_CHECK_REVIEW, "review_check", "check_id"),
            (_EFFECTIVENESS, "effectiveness", None),
        ):
            match = pattern.match(route_path)
            if match is not None:
                return operation, match.group("project_key"), match.group(group) if group else None
        return None

    @staticmethod
    def _validate_request(
        operation: str,
        payload: object,
    ) -> _FailureCorpusMutationRequest:
        if operation == "add_incident":
            return FailureCorpusIncidentMutationRequest.model_validate(payload)
        if operation == "review_pattern":
            return FailureCorpusPatternReviewRequest.model_validate(payload)
        if operation == "review_check":
            return FailureCorpusCheckReviewRequest.model_validate(payload)
        return FailureCorpusEffectivenessRequest.model_validate(payload)

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
                message="Stored failure-corpus idempotency result is malformed",
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus(status_raw),
            {str(key): value for key, value in body_raw.items()},
            correlation_id=correlation_id,
        )

    @staticmethod
    def _execute(
        corpus: _FailureCorpusPort,
        operation: str,
        project_key: str,
        target_id: str | None,
        wire_request: _FailureCorpusMutationRequest,
    ) -> (
        FailureCorpusIncidentMutationResponse
        | FailureCorpusPatternReviewResponse
        | FailureCorpusCheckReviewResponse
        | FailureCorpusEffectivenessResponse
    ):
        if operation == "add_incident":
            incident_request = cast(
                "FailureCorpusIncidentMutationRequest",
                wire_request,
            )
            incident_id = corpus.record_incident(
                IncidentCandidate(
                    project_key=project_key,
                    **incident_request.model_dump(mode="json", exclude={"op_id"}),
                ),
            )
            return FailureCorpusIncidentMutationResponse(incident_id=str(incident_id))
        if operation == "review_pattern":
            pattern_request = cast("FailureCorpusPatternReviewRequest", wire_request)
            pattern = corpus.confirm_pattern(
                PatternId(str(target_id)),
                pattern_request.decision,
                invariant=pattern_request.invariant,
                risk_level=pattern_request.risk_level,
                promotion_rule=pattern_request.promotion_rule,
                category=pattern_request.category,
            )
            return FailureCorpusPatternReviewResponse(
                pattern_id=str(pattern.pattern_id),
                decision=pattern_request.decision,
            )
        if operation == "review_check":
            check_request = cast("FailureCorpusCheckReviewRequest", wire_request)
            check = corpus.approve_check(
                CheckId(str(target_id)),
                check_request.decision,
                rejected_reason=check_request.rejected_reason,
            )
            return FailureCorpusCheckReviewResponse(
                check_id=str(check.check_id),
                decision=check_request.decision,
            )
        effectiveness_request = cast("FailureCorpusEffectivenessRequest", wire_request)
        report = corpus.report_effectiveness(window_days=effectiveness_request.window_days)
        return FailureCorpusEffectivenessResponse(
            window_days=report.window_days,
            updated_count=report.updated_count,
            deactivated_count=report.deactivated_count,
        )

    def _build_corpus(self, project_key: str) -> _FailureCorpusPort:
        if self._corpus_builder is not None:
            return cast("_FailureCorpusPort", self._corpus_builder(project_key))
        from agentkit.backend.bootstrap.composition_root import (
            build_failure_corpus,
            build_projection_accessor,
        )

        accessor = build_projection_accessor()
        return cast("_FailureCorpusPort", build_failure_corpus(accessor, project_key=project_key))

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
            error_code="failure_corpus_admin_forbidden",
            message="Failure-corpus mutations require a strategist session",
            correlation_id=correlation_id,
        )


__all__ = ["FailureCorpusRoutes"]
