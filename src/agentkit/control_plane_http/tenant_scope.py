"""Tenant-scope middleware: project_key path extraction and validation (AG3-090).

FK-72 §72.8.1: project_key is a mandatory path segment for all project-scoped
endpoints.  This middleware:

  1. Extracts ``project_key`` from the URL path (``/v1/projects/{key}/...``).
  2. Validates that the project exists (fail-closed: unknown -> 404).
  3. For mutation methods (POST/PUT/PATCH/DELETE), rejects archived projects
     with 403/``forbidden`` (fail-closed).
  4. For read methods (GET), archived projects pass through (read-only access
     is still allowed for observability purposes).

No business logic lives here; the middleware only consults ``ProjectRepository``
(the authoritative project existence/status source) and produces structured
``HttpResponse`` error objects.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.control_plane.models import ApiErrorResponse

if TYPE_CHECKING:
    from agentkit.control_plane_http.app import HttpResponse
    from agentkit.project_management.repository import ProjectRepository

logger = logging.getLogger(__name__)

_CORRELATION_HEADER = "X-Correlation-Id"
_PROJECT_KEY_PATTERN = re.compile(r"^/v1/projects/(?P<project_key>[^/]+)/")
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class TenantScopeMiddleware:
    """Validates project_key for project-scoped HTTP paths (FK-72 §72.8.1).

    Args:
        repository: Project persistence port.  Defaults to the state-backend
            ``StateBackendProjectRepository``.  Injectable for testing.
    """

    repository: ProjectRepository | None = None

    def _get_repository(self) -> ProjectRepository:
        if self.repository is not None:
            return self.repository
        from agentkit.state_backend.store.project_management_repository import (
            StateBackendProjectRepository,
        )

        return StateBackendProjectRepository()

    def validate(
        self,
        *,
        method: str,
        route_path: str,
        correlation_id: str,
    ) -> HttpResponse | None:
        """Validate the project_key extracted from ``route_path``.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE).
            route_path: The URL path (e.g. ``/v1/projects/myproj/stories``).
            correlation_id: Request correlation id for error responses.

        Returns:
            ``None`` when validation passes (project exists, not archived on
            mutation); an ``HttpResponse`` with 404/403 when it fails.
        """
        match = _PROJECT_KEY_PATTERN.match(route_path)
        if match is None:
            # Not a project-scoped path — nothing to validate.
            return None

        project_key = match.group("project_key")
        try:
            repo = self._get_repository()
            project = repo.get(project_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tenant-scope project lookup failed: %s", exc)
            return _error_http_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="project_lookup_unavailable",
                message="Project lookup temporarily unavailable",
                correlation_id=correlation_id,
            )

        if project is None:
            return _error_http_response(
                HTTPStatus.NOT_FOUND,
                error_code="project_not_found",
                message=f"Project {project_key!r} not found",
                correlation_id=correlation_id,
            )

        if project.archived_at is not None and method in _MUTATION_METHODS:
            return _error_http_response(
                HTTPStatus.FORBIDDEN,
                error_code="forbidden",
                message=f"Project {project_key!r} is archived; mutations are not allowed",
                correlation_id=correlation_id,
            )

        return None


def _error_http_response(
    status: HTTPStatus,
    *,
    error_code: str,
    message: str,
    correlation_id: str,
) -> HttpResponse:
    """Build a structured error HttpResponse (FAIL-CLOSED contract)."""
    from agentkit.control_plane_http.app import HttpResponse

    payload = ApiErrorResponse(
        error_code=error_code,
        error=message,
        correlation_id=correlation_id,
    ).model_dump(mode="json", exclude_none=True)
    body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return HttpResponse(
        status_code=int(status),
        body=body,
        headers=((_CORRELATION_HEADER, correlation_id),),
    )
