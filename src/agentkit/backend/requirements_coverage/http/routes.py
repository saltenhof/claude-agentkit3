"""Requirements-coverage HTTP routes (AG3-090, FK-72 §72.8.2, FK-40 §40.10).

Mounts under ``/v1/projects/{project_key}/coverage``.

Endpoints:
  GET /v1/projects/{key}/coverage/stories/{story_id}/are-evidence
      Read-only.  Returns ARE evidence for a story (FK-40 §40.10).

Thin adapter.  Backend absent -> 503 ``coverage_unavailable``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from http import HTTPStatus

from agentkit.backend.control_plane.models import (
    BcRouteResponse,
    bc_json_response,
    bc_unavailable_response,
)

_COVERAGE_ROOT = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/coverage(?:/(?P<rest>.*))?$"
)
_COVERAGE_UNAVAILABLE = "coverage_unavailable"
_COVERAGE_UNAVAILABLE_MESSAGE = "Requirements-coverage service is not available"
_COVERAGE_ARE_EVIDENCE = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/coverage/stories/(?P<story_id>[^/]+)/are-evidence$"
)

RequirementsCoverageRouteResponse = BcRouteResponse


@dataclass(frozen=True)
class RequirementsCoverageRoutes:
    """Route handler for the requirements-coverage BC HTTP surface.

    Args:
        service_available: When ``False`` all routes return 503.
    """

    service_available: bool = False

    def handle_get(
        self,
        route_path: str,
        _query: dict[str, list[str]],
        correlation_id: str,
    ) -> RequirementsCoverageRouteResponse | None:
        """Handle requirements-coverage GET routes or return None.

        Routes:
          - GET /v1/projects/{key}/coverage
          - GET /v1/projects/{key}/coverage/stories/{story_id}/are-evidence
              (FK-40 §40.10, read-only)
        """
        # Check the more-specific ARE evidence path first:
        are_match = _COVERAGE_ARE_EVIDENCE.match(route_path)
        if are_match is not None:
            if not self.service_available:
                return bc_unavailable_response(
                    _COVERAGE_UNAVAILABLE,
                    message=_COVERAGE_UNAVAILABLE_MESSAGE,
                    correlation_id=correlation_id,
                )
            return bc_json_response(
                HTTPStatus.OK,
                {
                    "project_key": are_match.group("project_key"),
                    "story_id": are_match.group("story_id"),
                    "are_evidence": [],
                },
                correlation_id=correlation_id,
            )

        # Generic coverage root:
        root_match = _COVERAGE_ROOT.match(route_path)
        if root_match is None:
            return None
        if not self.service_available:
            return bc_unavailable_response(
                _COVERAGE_UNAVAILABLE,
                message=_COVERAGE_UNAVAILABLE_MESSAGE,
                correlation_id=correlation_id,
            )
        return bc_json_response(
            HTTPStatus.OK,
            {"project_key": root_match.group("project_key"), "coverage": []},
            correlation_id=correlation_id,
        )

    def handle_post(
        self,
        route_path: str,
        _payload: object,
        correlation_id: str,
    ) -> RequirementsCoverageRouteResponse | None:
        """Handle requirements-coverage POST routes or return None."""
        # are-evidence is read-only (GET only per FK-40 §40.10).
        match = _COVERAGE_ROOT.match(route_path)
        if match is None:
            return None
        if not self.service_available:
            return bc_unavailable_response(
                _COVERAGE_UNAVAILABLE,
                message=_COVERAGE_UNAVAILABLE_MESSAGE,
                correlation_id=correlation_id,
            )
        return bc_json_response(
            HTTPStatus.ACCEPTED,
            {"project_key": match.group("project_key"), "status": "accepted"},
            correlation_id=correlation_id,
        )
