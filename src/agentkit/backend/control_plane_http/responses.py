"""HTTP response conversion helpers for the control-plane BFF."""


from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from agentkit.backend.control_plane.models import (
    ApiErrorResponse,
    ControlPlaneMutationResult,
    EdgeCommandMutationResult,
)
from agentkit.backend.control_plane.ownership_fence import ERROR_CODE_OWNERSHIP_TRANSFERRED
from agentkit.backend.control_plane_http.header_lookup import lookup_header_ci

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from agentkit.backend.auth.http.routes import AuthRouteResponse
    from agentkit.backend.auth.middleware import AuthMiddlewareResponse
    from agentkit.backend.concept_catalog.http.routes import ConceptRouteResponse
    from agentkit.backend.exceptions import ConfigError
    from agentkit.backend.execution_planning.http.routes import ExecutionPlanningRouteResponse
    from agentkit.backend.project_management.http.routes import ProjectRouteResponse
    from agentkit.backend.story_context_manager.http.routes import StoryRouteResponse
    from agentkit.backend.telemetry.http.routes import TelemetryRouteResponse
    from agentkit.integration_clients.multi_llm_hub.http.routes import MultiLlmHubRouteResponse


_CORRELATION_HEADER = "X-Correlation-Id"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HttpResponse:
    """Serializable HTTP response."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()
    stream: Iterable[bytes] | None = None


def _json_response(
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    correlation_id: str,
    headers: Sequence[tuple[str, str]] = (),
) -> HttpResponse:
    return HttpResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),) + tuple(headers),
    )


def _mutation_result_response(
    result: ControlPlaneMutationResult,
    *,
    correlation_id: str,
) -> HttpResponse:
    """Map a control-plane mutation result to its fail-closed HTTP status (AG3-138).

    A ``rejected`` result -- the fail-closed outcome of EVERY mutating control-plane
    entrypoint (``start``/``complete``/``fail``/``resume``/``closure``), including the
    AC10 open-reconcile/repair mutation lock -- maps to 409 CONFLICT; any other
    (committed / replayed) result maps to 201 CREATED. Centralizing this here keeps
    the rejected->409 wiring identical across phase mutations and closure completion,
    so no mutating entrypoint can return 2xx for a fail-closed rejection.

    AG3-142 (FK-91 §91.1a Rule 18): the ONE exception is the ex-owner
    ``ownership_transferred`` rejection, which maps to 403 FORBIDDEN instead of
    the generic 409 -- the caller is not merely conflicting with concurrent
    state, it no longer holds run-ownership at all. The structured
    ``ownership_conflict`` detail (reason, new owner, transfer instant) travels
    on the SAME ``ControlPlaneMutationResult`` body, embedded per the FK-91
    Rule 8 error contract (``error_code`` here; ``correlation_id`` via the
    ``X-Correlation-Id`` header on every response, Rule 7).

    AG3-141 (K4, IMPL-016): a busy-object-claim rejection additionally carries
    ``retry_after_seconds`` -- surfaced here as a ``Retry-After`` header (the
    deterministic wait contract; never a blocking wait). Every other rejection
    cause carries no such header (unchanged behaviour).
    """
    if result.status != "rejected":
        status = HTTPStatus.CREATED
    elif result.error_code == ERROR_CODE_OWNERSHIP_TRANSFERRED:
        status = HTTPStatus.FORBIDDEN
    else:
        status = HTTPStatus.CONFLICT
    headers: tuple[tuple[str, str], ...] = ()
    if result.retry_after_seconds is not None:
        headers = (("Retry-After", str(result.retry_after_seconds)),)
    return _json_response(
        status,
        result.model_dump(mode="json"),
        correlation_id=correlation_id,
        headers=headers,
    )


def _edge_command_result_response(
    result: EdgeCommandMutationResult,
    *,
    correlation_id: str,
) -> HttpResponse:
    """Map an Edge-Command-Queue result to its fail-closed HTTP status (AG3-145).

    Mirrors ``_mutation_result_response`` for the DEDICATED
    :class:`EdgeCommandMutationResult` shape: ``completed``/``replayed`` map to
    201 CREATED; a ``rejected`` result maps to 404 for an unknown/foreign
    ``command_id`` (``edge_command_not_found``), 403 for the ex-owner
    ``ownership_transferred`` payload (Rule 18), and 409 CONFLICT for every
    other fail-closed cause (double-completion, non-admitted, busy object --
    the busy-object cause additionally carries the K4 ``Retry-After`` header).
    """
    if result.status != "rejected":
        status = HTTPStatus.CREATED
    elif result.error_code == "edge_command_not_found":
        status = HTTPStatus.NOT_FOUND
    elif result.error_code == ERROR_CODE_OWNERSHIP_TRANSFERRED:
        status = HTTPStatus.FORBIDDEN
    else:
        status = HTTPStatus.CONFLICT
    headers: tuple[tuple[str, str], ...] = ()
    if result.retry_after_seconds is not None:
        headers = (("Retry-After", str(result.retry_after_seconds)),)
    return _json_response(
        status,
        result.model_dump(mode="json"),
        correlation_id=correlation_id,
        headers=headers,
    )


def _takeover_result_response(
    result: ControlPlaneMutationResult,
    *,
    correlation_id: str,
) -> HttpResponse:
    """Map ownership-transfer results to their dedicated HTTP contract."""
    if result.status == "pending_human_approval":
        status = HTTPStatus.ACCEPTED
    elif result.status in {"offered", "committed", "replayed"}:
        status = HTTPStatus.CREATED
    elif result.error_code == "agent_confirm_forbidden" or result.error_code == ERROR_CODE_OWNERSHIP_TRANSFERRED:
        status = HTTPStatus.FORBIDDEN
    else:
        status = HTTPStatus.CONFLICT
    headers: tuple[tuple[str, str], ...] = ()
    if result.retry_after_seconds is not None:
        headers = (("Retry-After", str(result.retry_after_seconds)),)
    return _json_response(
        status,
        result.model_dump(mode="json"),
        correlation_id=correlation_id,
        headers=headers,
    )


def _project_response_to_http_response(response: ProjectRouteResponse) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
    )


def _auth_response_to_http_response(response: AuthRouteResponse) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
    )


def _auth_middleware_response_to_http_response(
    response: AuthMiddlewareResponse,
) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
    )


def _concept_response_to_http_response(response: ConceptRouteResponse) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
    )


def _hub_response_to_http_response(response: MultiLlmHubRouteResponse) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
        stream=response.stream,
    )


def _planning_response_to_http_response(
    response: ExecutionPlanningRouteResponse,
) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
    )


def _story_response_to_http_response(response: StoryRouteResponse) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
    )


def _telemetry_response_to_http_response(
    response: TelemetryRouteResponse,
) -> HttpResponse:
    return HttpResponse(
        status_code=response.status_code,
        body=response.body,
        headers=response.headers,
        stream=response.stream,
    )


def _bc_response_to_http_response(response: object) -> HttpResponse:
    """Convert any BC route response (dataclass with status_code/body/headers)."""
    return HttpResponse(
        status_code=getattr(response, "status_code", 500),
        body=getattr(response, "body", b""),
        headers=getattr(response, "headers", ()),
    )


def _error_response(
    status: HTTPStatus,
    *,
    error_code: str,
    message: str,
    correlation_id: str,
    detail: object | None = None,
    headers: Sequence[tuple[str, str]] = (),
) -> HttpResponse:
    payload = ApiErrorResponse(
        error_code=error_code,
        error=message,
        correlation_id=correlation_id,
        detail=detail,
    ).model_dump(mode="json", exclude_none=True)
    return _json_response(
        status,
        payload,
        correlation_id=correlation_id,
        headers=headers,
    )


def _backend_requirement_response(
    error_code: str,
    exc: ConfigError,
    correlation_id: str,
) -> HttpResponse:
    """Map a backend-requirement ``ConfigError`` to a structured 503."""
    logger.warning("Control-plane backend requirement unmet: %s", exc)
    return _error_response(
        HTTPStatus.SERVICE_UNAVAILABLE,
        error_code=error_code,
        message=str(exc),
        correlation_id=correlation_id,
    )


def _decode_json_body(body: bytes, correlation_id: str) -> object | HttpResponse:
    try:
        return cast("object", json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error_response(
            HTTPStatus.BAD_REQUEST,
            error_code="invalid_json",
            message="Request body must be valid JSON",
            correlation_id=correlation_id,
        )


def _decode_optional_json_body(
    body: bytes, correlation_id: str
) -> object | HttpResponse:
    """Decode a request body that may legitimately be empty (DELETE routes).

    An empty body decodes to ``{}`` so a route needing no payload is unaffected;
    a non-empty body must still be valid JSON (fail-closed ``invalid_json`` on a
    malformed one). AG3-140: the token-revoke DELETE carries its client-supplied
    ``op_id`` (FK-91 §91.1a Rule 5) in this optional body.
    """
    if not body or not body.strip():
        return {}
    return _decode_json_body(body, correlation_id)


def _single_query_value(query: dict[str, list[str]], key: str) -> str | None:
    """Return the first value for ``key`` in a parsed query string, or ``None``."""
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _resolve_correlation_id(request_headers: Mapping[str, str] | None) -> str:
    # HTTP header names are case-insensitive (RFC 9110 §5.1). The official client
    # sends ``X-Correlation-Id`` but ``urllib`` (and intermediaries) may normalize
    # the casing on the wire, so an EXACT-case lookup would miss the client's id
    # and the control plane would mint a divergent ``req-<uuid>`` (FK-91 §91.1a
    # Rule #7 violation). Resolve the header case-insensitively so the client's
    # correlation id is adopted regardless of the transmitted casing.
    if request_headers is not None:
        provided = lookup_header_ci(request_headers, _CORRELATION_HEADER)
        if provided is not None:
            value = provided.strip()
            if value:
                return value
    return f"req-{uuid.uuid4().hex}"


def _has_header(headers: Sequence[tuple[str, str]], name: str) -> bool:
    normalized = name.lower()
    return any(key.lower() == normalized for key, _value in headers)
