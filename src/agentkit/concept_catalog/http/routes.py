"""Concept-catalog routes for the existing control-plane HTTP dispatcher.

``ControlPlaneApplication`` registers this adapter for the project-neutral
``/v1/concepts`` surface. The adapter exposes read-only catalog operations and
does not own compliance, lifecycle, or governance decisions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path

from agentkit.concept_catalog.errors import ConceptRefNotFoundError
from agentkit.concept_catalog.index import ConceptIndex

_CORRELATION_HEADER = "X-Correlation-Id"
_CONTENT_TYPE_HEADER = "Content-Type"
_CONCEPT_DETAIL_PATH = re.compile(r"^/v1/concepts/(?P<concept_ref>[^/]+)$")
_CONCEPT_CONTENT_PATH = re.compile(r"^/v1/concepts/(?P<concept_ref>[^/]+)/content$")


@dataclass(frozen=True)
class ConceptRouteResponse:
    """Serializable response produced by the concept-catalog HTTP adapter."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


class ConceptCatalogRoutes:
    """Route handler for the project-neutral concept catalog surface."""

    def __init__(self, index: ConceptIndex | None = None) -> None:
        if index is None:
            root = Path(__file__).resolve().parents[4] / "concept"
            index = ConceptIndex(root)
            index.load()
        self._index = index

    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> ConceptRouteResponse | None:
        """Handle concept-catalog GET routes or return None."""

        if route_path == "/v1/concepts":
            return self._handle_list(query, correlation_id)
        if route_path == "/v1/concepts/search":
            return self._handle_search(query, correlation_id)

        content_match = _CONCEPT_CONTENT_PATH.match(route_path)
        if content_match is not None:
            return self._handle_content(content_match.group("concept_ref"), correlation_id)

        detail_match = _CONCEPT_DETAIL_PATH.match(route_path)
        if detail_match is None:
            return None
        return self._handle_detail(detail_match.group("concept_ref"), correlation_id)

    def _handle_list(
        self,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> ConceptRouteResponse:
        refs = self._index.list(
            layer=_single_query_value(query, "layer"),
            status=_single_query_value(query, "status"),
            domain=_single_query_value(query, "domain"),
        )
        return _json_response(
            HTTPStatus.OK,
            {"concepts": [ref.model_dump(mode="json") for ref in refs]},
            correlation_id=correlation_id,
        )

    def _handle_detail(
        self,
        concept_ref: str,
        correlation_id: str,
    ) -> ConceptRouteResponse:
        ref = self._index.get(concept_ref)
        if ref is None:
            return _not_found_response(concept_ref, correlation_id)
        return _json_response(
            HTTPStatus.OK,
            {
                "concept": ref.model_dump(mode="json"),
                "backlinks": self._index.backlinks(concept_ref).model_dump(mode="json"),
            },
            correlation_id=correlation_id,
        )

    def _handle_content(
        self,
        concept_ref: str,
        correlation_id: str,
    ) -> ConceptRouteResponse:
        try:
            body = self._index.content(concept_ref)
        except ConceptRefNotFoundError:
            return _not_found_response(concept_ref, correlation_id)
        return ConceptRouteResponse(
            status_code=int(HTTPStatus.OK),
            body=body.encode("utf-8"),
            headers=(
                (_CORRELATION_HEADER, correlation_id),
                (_CONTENT_TYPE_HEADER, "text/markdown; charset=utf-8"),
            ),
        )

    def _handle_search(
        self,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> ConceptRouteResponse:
        q = _single_query_value(query, "q")
        if q is None:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="missing_query",
                message="Missing required query parameter: q",
                correlation_id=correlation_id,
            )
        hits = self._index.search(q, limit=_limit_query_value(query, "limit"))
        return _json_response(
            HTTPStatus.OK,
            {"hits": [hit.model_dump(mode="json") for hit in hits]},
            correlation_id=correlation_id,
        )


def _single_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _limit_query_value(query: dict[str, list[str]], key: str) -> int:
    raw_value = _single_query_value(query, key)
    if raw_value is None:
        return 20
    try:
        parsed = int(raw_value)
    except ValueError:
        return 20
    return max(parsed, 0)


def _json_response(
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    correlation_id: str,
) -> ConceptRouteResponse:
    return ConceptRouteResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=(
            (_CORRELATION_HEADER, correlation_id),
            (_CONTENT_TYPE_HEADER, "application/json"),
        ),
    )


def _not_found_response(concept_ref: str, correlation_id: str) -> ConceptRouteResponse:
    return _error_response(
        HTTPStatus.NOT_FOUND,
        error_code="concept_not_found",
        message="Concept reference not found",
        correlation_id=correlation_id,
        detail={"concept_ref": concept_ref},
    )


def _error_response(
    status: HTTPStatus,
    *,
    error_code: str,
    message: str,
    correlation_id: str,
    detail: object | None = None,
) -> ConceptRouteResponse:
    payload: dict[str, object] = {
        "error_code": error_code,
        "error": message,
        "correlation_id": correlation_id,
    }
    if detail is not None:
        payload["detail"] = detail
    return _json_response(status, payload, correlation_id=correlation_id)
