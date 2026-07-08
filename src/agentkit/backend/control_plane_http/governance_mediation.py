"""Governance and telemetry mediation handlers for the control-plane BFF."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.control_plane.models import (
    GuardCounterMutationRequest,
    TelemetryEventIngestRequest,
    op_id_validation_error,
)
from agentkit.backend.control_plane_http.responses import (
    HttpResponse,
    _error_response,
    _json_response,
    _single_query_value,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane.guard_counter import ControlPlaneGuardCounterService
    from agentkit.backend.control_plane.telemetry import ControlPlaneTelemetryService
    from agentkit.backend.control_plane.worker_health import ControlPlaneWorkerHealthService

logger = logging.getLogger(__name__)


class _GovernanceMediationHandlers:
    """Governance hook-mediation HTTP handlers (AG3-129), split out of the app.

    Extracted from :class:`ControlPlaneApplication` so that transport class stays
    within the per-class LOC budget (``PY_CLASS_MAX_LOC_800``) WITHOUT any
    behaviour change: these handlers depend only on the injected mediation
    services and the module-level response helpers, never on the app's routing
    state. The three collaborators are supplied by
    ``ControlPlaneApplication.__init__``; they are declared here as annotations
    for the type checker (the mixin never constructs them).
    """

    _telemetry_service: ControlPlaneTelemetryService
    _guard_counter_service: ControlPlaneGuardCounterService
    _worker_health_service: ControlPlaneWorkerHealthService

    def _handle_post_telemetry(
        self,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        try:
            request = TelemetryEventIngestRequest.model_validate(payload)
            accepted = self._telemetry_service.ingest_event(request)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_telemetry_event_payload",
                message="Invalid telemetry event payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except RuntimeError as exc:
            logger.warning("Control-plane telemetry ingest unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="telemetry_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.CREATED,
            accepted.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_post_guard_counter(
        self,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        """Apply a guard-invocation counter mutation (AG3-129, FK-61 §61.4.3)."""
        from agentkit.backend.story_context_manager.errors import (
            IdempotencyMismatchError,
        )

        try:
            request = GuardCounterMutationRequest.model_validate(payload)
            accepted = self._guard_counter_service.apply(request)
        except ValidationError as exc:
            # AG3-140 (FK-91 §91.1a Rule 5, AC1): a missing/empty op_id fails
            # closed with 422, distinct from an ordinary 400 payload-shape defect.
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY
                if op_id_validation_error(exc)
                else HTTPStatus.BAD_REQUEST,
                error_code="invalid_guard_counter_payload",
                message="Invalid guard-counter mutation payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except IdempotencyMismatchError as exc:
            # FK-91 §91.1a Rule 5: same op_id + different body -> fail-closed 409.
            return _error_response(
                HTTPStatus.CONFLICT,
                error_code="idempotency_mismatch",
                message=str(exc),
                correlation_id=correlation_id,
                detail=exc.detail,
            )
        except RuntimeError as exc:
            logger.warning("Guard-counter mutation unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="guard_counter_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.CREATED,
            accepted.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_get_worker_health(
        self,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse:
        """Read canonical worker-health state (AG3-129, FK-30 §30.10)."""
        story_id = _single_query_value(query, "story_id")
        worker_id = _single_query_value(query, "worker_id")
        if not story_id or not worker_id:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_worker_health_query",
                message="story_id and worker_id query parameters are required",
                correlation_id=correlation_id,
            )
        try:
            result = self._worker_health_service.load(
                story_id=story_id, worker_id=worker_id
            )
        except RuntimeError as exc:
            logger.warning("Worker-health read unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="worker_health_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_post_worker_health(
        self,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        """Write canonical worker-health state (AG3-129, FK-30 §30.10)."""
        try:
            accepted = self._worker_health_service.save(payload)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_worker_health_payload",
                message="Invalid worker-health state payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        except RuntimeError as exc:
            logger.warning("Worker-health write unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="worker_health_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.CREATED,
            accepted.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def _handle_get_telemetry_events(
        self,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse:
        """Read canonical execution events for one scope (AG3-129)."""
        project_key = _single_query_value(query, "project_key")
        story_id = _single_query_value(query, "story_id")
        event_type = _single_query_value(query, "event_type")
        if not project_key or not story_id:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_telemetry_query",
                message="project_key and story_id query parameters are required",
                correlation_id=correlation_id,
            )
        try:
            result = self._telemetry_service.query_events(
                project_key=project_key,
                story_id=story_id,
                event_type=event_type,
            )
        except RuntimeError as exc:
            logger.warning("Telemetry read unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="telemetry_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            result.model_dump(mode="json"),
            correlation_id=correlation_id,
        )
