"""Project-edge read handlers for the control-plane HTTP BFF."""


from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.control_plane_http.responses import (
    HttpResponse,
    _backend_requirement_response,
    _bc_response_to_http_response,
    _error_response,
    _json_response,
    _single_query_value,
)
from agentkit.backend.exceptions import ConfigError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
    from agentkit.backend.project_management.read_model_routes import ReadModelRoutes


def _handle_healthz(method: str, correlation_id: str) -> HttpResponse:
    """Return the /healthz response (200 OK for GET, 405 for anything else)."""
    if method != "GET":
        return _error_response(
            HTTPStatus.METHOD_NOT_ALLOWED,
            error_code="method_not_allowed",
            message="Method not allowed",
            correlation_id=correlation_id,
            headers=(("Allow", "GET"),),
        )
    return _json_response(
        HTTPStatus.OK,
        {"status": "ok"},
        correlation_id=correlation_id,
    )


def _handle_get_operation(
    runtime_service: ControlPlaneRuntimeService,
    op_id: str,
    correlation_id: str,
) -> HttpResponse:
    """Return the project-edge operation status (module-level helper, AG3-105 LOC split)."""
    try:
        result = runtime_service.get_operation(op_id)
    except ConfigError as exc:
        return _backend_requirement_response(
            "project_edge_reconcile_unavailable", exc, correlation_id
        )
    except RuntimeError as exc:
        logger.warning("Project-edge reconcile unavailable: %s", exc)
        return _error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            error_code="project_edge_reconcile_unavailable",
            message=str(exc),
            correlation_id=correlation_id,
        )
    if result is None:
        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="operation_not_found",
            message="Operation not found",
            correlation_id=correlation_id,
        )
    return _json_response(
        HTTPStatus.OK,
        result.model_dump(mode="json"),
        correlation_id=correlation_id,
    )


def _handle_get_push_freshness(
    runtime_service: ControlPlaneRuntimeService,
    run_id: str,
    query: dict[str, list[str]],
    correlation_id: str,
) -> HttpResponse:
    """``GET .../story-runs/{run_id}/push-freshness`` (FK-10 §10.2.4b, AG3-147 AC5).

    Module-level helper (AG3-147 LOC split, PY_CLASS_MAX_LOC_800): keeps the
    read-model route out of ``ControlPlaneApplication``'s class body.
    ``project_key``/``story_id`` are mandatory query parameters (a GET carries no
    body). Read-only, no lock/claim. The read surface is Postgres-only (K5): a
    non-Postgres backend fails closed with a stable
    ``push_freshness_unavailable`` 503.
    """
    project_key = _single_query_value(query, "project_key")
    story_id = _single_query_value(query, "story_id")
    if not project_key or not story_id:
        return _error_response(
            HTTPStatus.BAD_REQUEST,
            error_code="invalid_push_freshness_query",
            message="project_key and story_id query parameters are required",
            correlation_id=correlation_id,
        )
    try:
        result = runtime_service.list_push_freshness(
            run_id, project_key=project_key, story_id=story_id,
        )
    except ConfigError as exc:
        return _backend_requirement_response(
            "push_freshness_unavailable", exc, correlation_id
        )
    except RuntimeError as exc:
        logger.warning("Push-freshness read unavailable: %s", exc)
        return _error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            error_code="push_freshness_unavailable",
            message=str(exc),
            correlation_id=correlation_id,
        )
    return _json_response(
        HTTPStatus.OK,
        result.model_dump(mode="json"),
        correlation_id=correlation_id,
    )


def _handle_get_push_ownership(
    runtime_service: ControlPlaneRuntimeService,
    run_id: str,
    query: dict[str, list[str]],
    correlation_id: str,
) -> HttpResponse:
    """``GET .../story-runs/{run_id}/push-ownership`` (FK-15 §15.5.4, AG3-147 AC6).

    The bounded online-ownership check the official Edge-Push-Gate runs
    immediately before a ``story/*`` push. ``project_key``/``story_id``/
    ``session_id`` are mandatory query parameters (a GET carries no body).
    Read-only, no lock/claim. Postgres-only (K5): a non-Postgres backend fails
    closed with a stable ``push_ownership_unavailable`` 503.
    """
    project_key = _single_query_value(query, "project_key")
    story_id = _single_query_value(query, "story_id")
    session_id = _single_query_value(query, "session_id")
    if not project_key or not story_id or not session_id:
        return _error_response(
            HTTPStatus.BAD_REQUEST,
            error_code="invalid_push_ownership_query",
            message="project_key, story_id and session_id query parameters are required",
            correlation_id=correlation_id,
        )
    try:
        result = runtime_service.confirm_push_ownership(
            run_id, project_key=project_key, story_id=story_id, session_id=session_id,
        )
    except ConfigError as exc:
        return _backend_requirement_response(
            "push_ownership_unavailable", exc, correlation_id
        )
    except RuntimeError as exc:
        logger.warning("Push-ownership read unavailable: %s", exc)
        return _error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            error_code="push_ownership_unavailable",
            message=str(exc),
            correlation_id=correlation_id,
        )
    return _json_response(
        HTTPStatus.OK,
        result.model_dump(mode="json"),
        correlation_id=correlation_id,
    )


def _handle_get_open_commands(
    runtime_service: ControlPlaneRuntimeService,
    run_id: str,
    query: dict[str, list[str]],
    correlation_id: str,
) -> HttpResponse:
    """``GET .../story-runs/{run_id}/commands`` (FK-91 §91.1b, AG3-145 AC1).

    Module-level helper (AG3-147 LOC split, PY_CLASS_MAX_LOC_800): keeps the
    Edge-Command-Queue GET out of ``ControlPlaneApplication``'s class body.
    ``project_key``/``session_id`` are mandatory query parameters (a GET carries
    no body); the fail-closed session scoping happens at the store query, never
    at this validation.
    """
    project_key = _single_query_value(query, "project_key")
    session_id = _single_query_value(query, "session_id")
    if not project_key or not session_id:
        return _error_response(
            HTTPStatus.BAD_REQUEST,
            error_code="invalid_edge_commands_query",
            message="project_key and session_id query parameters are required",
            correlation_id=correlation_id,
        )
    try:
        result = runtime_service.list_and_ack_open_commands(
            run_id, project_key=project_key, session_id=session_id,
        )
    except ConfigError as exc:
        return _backend_requirement_response(
            "edge_commands_unavailable", exc, correlation_id
        )
    except RuntimeError as exc:
        logger.warning("Edge-command list unavailable: %s", exc)
        return _error_response(
            HTTPStatus.SERVICE_UNAVAILABLE,
            error_code="edge_commands_unavailable",
            message=str(exc),
            correlation_id=correlation_id,
        )
    return _json_response(
        HTTPStatus.OK,
        result.model_dump(mode="json"),
        correlation_id=correlation_id,
    )


def _read_only_method_not_allowed(
    read_model_routes: ReadModelRoutes,
    route_path: str,
    correlation_id: str,
) -> HttpResponse | None:
    """Return 405 for a mutation on an AG3-091 read-only path, else None.

    Only called for POST/PUT/PATCH (GET/DELETE return earlier).  Reuses the
    verb-agnostic ``ReadModelRoutes`` 405-matcher (all mutation verbs map to
    the same ``_method_not_allowed_if_matches`` with ``Allow: GET``) so the
    read-only-endpoint decision lives in exactly one place (SSOT).  Running
    this BEFORE ``_decode_json_body`` ensures the 405 fires regardless of the
    request body — an empty or non-JSON body on a read-only path must NOT
    degrade to ``400 invalid_json`` (FAIL-CLOSED, AC1/AC5).
    """
    response = read_model_routes.handle_post(route_path, None, correlation_id)
    if response is not None:
        return _bc_response_to_http_response(response)
    return None
