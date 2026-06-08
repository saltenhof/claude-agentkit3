"""Shared response type used by all BC http/ adapters (AG3-090).

Each BC http/ module uses its own named response class (following the pattern
of existing modules like ``ProjectRouteResponse``, ``StoryRouteResponse``).
This module provides the shared helper for building structured 503 responses
when a consuming backend service is unavailable (FAIL-CLOSED, ZERO DEBT).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from http import HTTPStatus

from agentkit.control_plane.models import ApiErrorResponse

_CORRELATION_HEADER = "X-Correlation-Id"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BcRouteResponse:
    """Serializable response produced by a BC HTTP adapter.

    Attributes:
        status_code: HTTP status code.
        body: Response body bytes.
        headers: Response headers.
    """

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


def bc_json_response(
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    correlation_id: str,
) -> BcRouteResponse:
    """Build a JSON BcRouteResponse."""
    return BcRouteResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),),
    )


def bc_error_response(
    status: HTTPStatus,
    *,
    error_code: str,
    message: str,
    correlation_id: str,
    detail: object | None = None,
) -> BcRouteResponse:
    """Build a structured error BcRouteResponse (typed Pydantic, ARCH-55)."""
    payload = ApiErrorResponse(
        error_code=error_code,
        error=message,
        correlation_id=correlation_id,
        detail=detail,
    ).model_dump(mode="json", exclude_none=True)
    return BcRouteResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),),
    )


def bc_unavailable_response(
    error_code: str,
    *,
    message: str,
    correlation_id: str,
) -> BcRouteResponse:
    """Return a structured 503 when the backend service is unavailable.

    FAIL-CLOSED: no silent empty-200 or bare 500.  ``error_code`` must be
    ``*_unavailable`` (ARCH-55 english, stable wire key).
    """
    logger.warning("BC service unavailable (%s): %s", error_code, message)
    return bc_error_response(
        HTTPStatus.SERVICE_UNAVAILABLE,
        error_code=error_code,
        message=message,
        correlation_id=correlation_id,
    )
