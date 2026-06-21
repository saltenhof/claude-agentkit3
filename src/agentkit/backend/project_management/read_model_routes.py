"""Project-scoped frontend read-model routes for AG3-091.

Implements six read-only GET endpoints (FK-91 §91.1a):
  GET /v1/projects/{key}/execution-input/limits
  GET /v1/projects/{key}/mode-lock
  GET /v1/projects/{key}/stories/counters
  GET /v1/projects/{key}/stories/{story_id}/flow
  GET /v1/projects/{key}/coverage/stories/{story_id}/acceptance
  GET /v1/projects/{key}/coverage/stories/{story_id}/are-evidence

SSOT: mode-lock and counters delegate to the authoritative service functions.
No snapshot/next surface, no second triage/selector (AG3-100 boundary).

Flow derivation (AG3-091 R3 — position-based algorithm):
  The flow snapshot is derived from story.status + the SINGLE current runtime
  PhaseState (load_phase_state_global) using position-based index comparison.
  No multi-phase persistence is required:
    - story.status == Done -> ALL phases done
    - story.status in {Backlog, Approved, Cancelled} OR no runtime -> ALL pending
    - otherwise: phases BEFORE the current runtime phase -> done;
      phases AFTER -> pending; current phase -> active (substeps from runtime)
  See ``build_story_flow_snapshot`` in read_models.py for the full algorithm.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import (
    ApiErrorResponse,
    BcRouteResponse,
    bc_error_response,
    bc_json_response,
)
from agentkit.backend.project_management.read_models import (
    build_are_evidence,
    build_coverage_acceptance,
    build_execution_limits,
    build_mode_lock,
    build_story_counters,
    build_story_flow_snapshot,
)
from agentkit.backend.story.repository import StoryRepository as _StoryRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.execution_planning.repository import ParallelizationConfigRepository
    from agentkit.backend.pipeline_engine.phase_executor import PhaseState
    from agentkit.backend.project_management.repository import ProjectRepository
    from agentkit.backend.requirements_coverage import AreClient
    from agentkit.backend.requirements_coverage.repository import StoryAreLinkRepository
    from agentkit.backend.story_context_manager.service import StoryService

logger = logging.getLogger(__name__)

_CORRELATION_HEADER = "X-Correlation-Id"

# ---------------------------------------------------------------------------
# Path patterns — project-scoped
# ---------------------------------------------------------------------------

_LIMITS_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/execution-input/limits$"
)
_MODE_LOCK_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/mode-lock$"
)
_COUNTERS_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/counters$"
)
_FLOW_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/(?P<story_id>[^/]+)/flow$"
)
_ACCEPTANCE_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/coverage/stories/(?P<story_id>[^/]+)/acceptance$"
)
_ARE_EVIDENCE_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/coverage/stories/(?P<story_id>[^/]+)/are-evidence$"
)

# All read-only patterns in a tuple for 405 detection (ordered most-specific first).
_READ_ONLY_PATTERNS = (
    _ARE_EVIDENCE_PATH,
    _ACCEPTANCE_PATH,
    _FLOW_PATH,
    _COUNTERS_PATH,
    _MODE_LOCK_PATH,
    _LIMITS_PATH,
)

_NOT_FOUND_CODE = "project_not_found"
_NOT_FOUND_MESSAGE = "Project not found"
_STORY_NOT_FOUND_CODE = "story_not_found"
_STORY_NOT_FOUND_MESSAGE_TEMPLATE = "Story {story_id!r} not found"

ReadModelRouteResponse = BcRouteResponse


@dataclass(frozen=True)
class ReadModelRoutes:
    """Route handler for the six AG3-091 project-scoped read-model endpoints.

    Args:
        project_repository: Project stammdaten port.
        story_service: story_context_manager read service.
        config_repository: Parallelization config repository (caps source).
        are_link_repository: StoryAreLink read port (AG3-077).
        are_client: Optional ARE REST client for live coverage status
            (FK-40 §40.5b.6). When ``None``, the route resolves the client
            per-request from ``project.configuration.are_url``.  When links
            exist but no ARE URL is configured for the project, the endpoint
            returns 503 ``are_unavailable`` (FAIL-CLOSED).  The ARE HTTP
            transport is the only allowed fake boundary (AC10).
        phase_state_loader: Callable that resolves the current
            :class:`~agentkit.backend.pipeline_engine.phase_executor.PhaseState` for
            a story by story_id.  Defaults to
            ``agentkit.backend.story.repository.load_phase_state_global`` (production
            wiring: SQLite backend reads ``phase_states`` table from
            ``Path.cwd()``).  Integration tests inject a closure that passes
            the ephemeral ``tmp_path`` as ``store_dir``.
    """

    project_repository: ProjectRepository
    story_service: StoryService
    config_repository: ParallelizationConfigRepository
    are_link_repository: StoryAreLinkRepository
    are_client: AreClient | None = field(default=None)
    phase_state_loader: Callable[[str], PhaseState | None] = field(
        default_factory=lambda: _StoryRepository().load_phase_state
    )

    def handle_get(
        self,
        route_path: str,
        _query: dict[str, list[str]],
        correlation_id: str,
    ) -> ReadModelRouteResponse | None:
        """Handle AG3-091 GET routes or return None.

        Route resolution uses most-specific patterns first to avoid ambiguity
        between paths that share a prefix (e.g. ``/coverage/stories/{id}/are-evidence``
        before ``/coverage/stories/{id}/acceptance``).

        Args:
            route_path: The URL path segment to match.
            _query: Parsed query string (not used by these routes).
            correlation_id: Correlation id echoed into every response.

        Returns:
            A :class:`ReadModelRouteResponse` when the path matches, or
            ``None`` to signal the dispatcher to continue to the next handler.
        """
        are_match = _ARE_EVIDENCE_PATH.match(route_path)
        if are_match is not None:
            return self._handle_are_evidence(
                are_match.group("project_key"),
                are_match.group("story_id"),
                correlation_id,
            )

        acc_match = _ACCEPTANCE_PATH.match(route_path)
        if acc_match is not None:
            return self._handle_acceptance(
                acc_match.group("project_key"),
                acc_match.group("story_id"),
                correlation_id,
            )

        flow_match = _FLOW_PATH.match(route_path)
        if flow_match is not None:
            return self._handle_flow(
                flow_match.group("project_key"),
                flow_match.group("story_id"),
                correlation_id,
            )

        counters_match = _COUNTERS_PATH.match(route_path)
        if counters_match is not None:
            return self._handle_counters(
                counters_match.group("project_key"),
                correlation_id,
            )

        mode_match = _MODE_LOCK_PATH.match(route_path)
        if mode_match is not None:
            return self._handle_mode_lock(
                mode_match.group("project_key"),
                correlation_id,
            )

        limits_match = _LIMITS_PATH.match(route_path)
        if limits_match is not None:
            return self._handle_limits(
                limits_match.group("project_key"),
                correlation_id,
            )

        return None

    def handle_post(
        self,
        route_path: str,
        _payload: object,
        correlation_id: str,
    ) -> ReadModelRouteResponse | None:
        """POST on a read-only AG3-091 path returns 405; otherwise None.

        Args:
            route_path: The URL path segment.
            _payload: Ignored request body.
            correlation_id: Correlation id.

        Returns:
            405 response when the path is a known read-only endpoint;
            ``None`` otherwise.
        """
        return self._method_not_allowed_if_matches(route_path, correlation_id)

    def handle_put(
        self,
        route_path: str,
        _payload: object,
        correlation_id: str,
    ) -> ReadModelRouteResponse | None:
        """PUT on a read-only AG3-091 path returns 405; otherwise None."""
        return self._method_not_allowed_if_matches(route_path, correlation_id)

    def handle_patch(
        self,
        route_path: str,
        _payload: object,
        correlation_id: str,
    ) -> ReadModelRouteResponse | None:
        """PATCH on a read-only AG3-091 path returns 405; otherwise None."""
        return self._method_not_allowed_if_matches(route_path, correlation_id)

    def handle_delete(
        self,
        route_path: str,
        correlation_id: str,
    ) -> ReadModelRouteResponse | None:
        """DELETE on a read-only AG3-091 path returns 405; otherwise None."""
        return self._method_not_allowed_if_matches(route_path, correlation_id)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _method_not_allowed_if_matches(
        self,
        route_path: str,
        correlation_id: str,
    ) -> ReadModelRouteResponse | None:
        """Return 405 with ``Allow: GET`` if the path is a known read-only endpoint.

        AC1/AC5: mutation on a read-only endpoint must return 405.
        """
        for pattern in _READ_ONLY_PATTERNS:
            if pattern.match(route_path):
                payload = ApiErrorResponse(
                    error_code="method_not_allowed",
                    error="This endpoint is read-only",
                    correlation_id=correlation_id,
                ).model_dump(mode="json", exclude_none=True)
                return BcRouteResponse(
                    status_code=int(HTTPStatus.METHOD_NOT_ALLOWED),
                    body=json.dumps(payload, sort_keys=True).encode("utf-8"),
                    headers=(
                        (_CORRELATION_HEADER, correlation_id),
                        ("Allow", "GET"),
                    ),
                )
        return None

    def _project_exists(self, project_key: str) -> bool:
        return self.project_repository.get(project_key) is not None

    def _not_found(self, correlation_id: str) -> ReadModelRouteResponse:
        return bc_error_response(
            HTTPStatus.NOT_FOUND,
            error_code=_NOT_FOUND_CODE,
            message=_NOT_FOUND_MESSAGE,
            correlation_id=correlation_id,
        )

    def _story_not_found(
        self,
        story_id: str,
        correlation_id: str,
    ) -> ReadModelRouteResponse:
        return bc_error_response(
            HTTPStatus.NOT_FOUND,
            error_code=_STORY_NOT_FOUND_CODE,
            message=_STORY_NOT_FOUND_MESSAGE_TEMPLATE.format(story_id=story_id),
            correlation_id=correlation_id,
        )

    def _handle_limits(
        self,
        project_key: str,
        correlation_id: str,
    ) -> ReadModelRouteResponse:
        if not self._project_exists(project_key):
            return self._not_found(correlation_id)
        config = self.config_repository.get(project_key)
        limits = build_execution_limits(project_key, config)
        return bc_json_response(
            HTTPStatus.OK,
            {"execution_limits": limits.model_dump(mode="json")},
            correlation_id=correlation_id,
        )

    def _handle_mode_lock(
        self,
        project_key: str,
        correlation_id: str,
    ) -> ReadModelRouteResponse:
        if not self._project_exists(project_key):
            return self._not_found(correlation_id)
        stories = self.story_service.list_stories_with_dependencies(project_key)
        mode_lock = build_mode_lock(project_key, stories)
        return bc_json_response(
            HTTPStatus.OK,
            {"mode_lock": mode_lock.model_dump(mode="json")},
            correlation_id=correlation_id,
        )

    def _handle_counters(
        self,
        project_key: str,
        correlation_id: str,
    ) -> ReadModelRouteResponse:
        if not self._project_exists(project_key):
            return self._not_found(correlation_id)
        stories = self.story_service.list_stories_with_dependencies(project_key)
        counters = build_story_counters(project_key, stories)
        return bc_json_response(
            HTTPStatus.OK,
            {"story_counters": counters.model_dump(mode="json")},
            correlation_id=correlation_id,
        )

    def _handle_flow(
        self,
        project_key: str,
        story_id: str,
        correlation_id: str,
    ) -> ReadModelRouteResponse:
        if not self._project_exists(project_key):
            return self._not_found(correlation_id)
        story = self.story_service.get_story(story_id)
        if story is None:
            return self._story_not_found(story_id, correlation_id)
        # ERROR D fix: project_key scope check (FK-73 §73.5, AC7)
        if story.project_key != project_key:
            return self._story_not_found(story_id, correlation_id)
        phase_state_or_error = self._load_current_phase_state(
            story_id, correlation_id
        )
        if isinstance(phase_state_or_error, BcRouteResponse):
            return phase_state_or_error
        is_fast = str(getattr(story, "mode", None)) == "fast"
        story_status = str(getattr(story, "status", "Backlog"))
        snapshot = build_story_flow_snapshot(
            story_id,
            story_status=story_status,
            is_fast_mode=is_fast,
            current_phase_state=phase_state_or_error,
        )
        return bc_json_response(
            HTTPStatus.OK,
            {"story_flow_snapshot": snapshot.model_dump(mode="json")},
            correlation_id=correlation_id,
        )

    def _load_current_phase_state(
        self,
        story_id: str,
        correlation_id: str,
    ) -> object | None | ReadModelRouteResponse:
        """Load the single current PhaseState for a story (FK-39, FAIL-CLOSED).

        Delegates to ``self.phase_state_loader`` (default:
        ``agentkit.backend.story.repository.load_phase_state_global``) to read the
        canonical runtime ``phase_states`` table (one row per story, written
        by the real PhaseExecutor write path).

        Returns the raw PhaseState when the story has been started, or ``None``
        when no phase state exists yet (story not started -> all phases pending).

        FAIL-CLOSED: infrastructure errors return a structured 503 response.
        A legitimately-unstarted story (no rows in ``phase_states``) returns
        ``None`` without error (all-phases-pending is the correct initial state,
        NOT an error).

        Args:
            story_id: Story identifier.
            correlation_id: Correlation id for structured error responses.

        Returns:
            The :class:`PhaseState` for the current phase, ``None`` for
            unstarted stories, or a 503 :class:`ReadModelRouteResponse` on
            infrastructure failure.
        """
        try:
            return self.phase_state_loader(story_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "phase-state load failed for story %r: %s",
                story_id,
                exc,
            )
            # FAIL-CLOSED: infrastructure failure is a structured error, not
            # a silent fall-back to all-pending.
            return bc_error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="flow_unavailable",
                message="Phase-state projection unavailable",
                correlation_id=correlation_id,
            )

    def _handle_acceptance(
        self,
        project_key: str,
        story_id: str,
        correlation_id: str,
    ) -> ReadModelRouteResponse:
        if not self._project_exists(project_key):
            return self._not_found(correlation_id)
        story_detail = self.story_service.get_story_detail(story_id)
        if story_detail is None:
            return self._story_not_found(story_id, correlation_id)
        _story, spec = story_detail
        # ERROR D fix: project_key scope check (FK-73 §73.5, AC7)
        if _story.project_key != project_key:
            return self._story_not_found(story_id, correlation_id)
        links = self.are_link_repository.list_by_story(story_id)
        acceptance_criteria: list[str] = []
        if spec is not None:
            raw_ac = getattr(spec, "acceptance_criteria", None) or []
            acceptance_criteria = [str(ac) for ac in raw_ac]
        coverage = build_coverage_acceptance(
            story_id, project_key, links, acceptance_criteria
        )
        return bc_json_response(
            HTTPStatus.OK,
            {"story_coverage_acceptance": coverage.model_dump(mode="json")},
            correlation_id=correlation_id,
        )

    def _resolve_are_client(self, project_key: str) -> AreClient | None:
        """Resolve the AreClient for the given project (per-request, FAIL-CLOSED).

        When an explicit ``are_client`` was injected (e.g. in tests via a fake
        ARE transport), that client is returned as-is.  Otherwise the client is
        built from ``project.configuration.are_url`` (FK-40 §40.5b.6).

        Returns ``None`` when ARE is not configured for the project
        (``are_url`` is ``None`` or the project is missing).  The caller
        is responsible for converting this into a 503 when links exist
        (FAIL-CLOSED, ERROR 2 fix).

        Args:
            project_key: Project key to load configuration for.

        Returns:
            A configured :class:`AreClient`, or ``None`` when ARE is off.
        """
        if self.are_client is not None:
            return self.are_client
        project = self.project_repository.get(project_key)
        if project is None:
            return None
        are_url = project.configuration.are_url
        if not are_url:
            return None
        from agentkit.backend.requirements_coverage import AreClient as _AreClient

        return _AreClient(are_url)

    def _handle_are_evidence(
        self,
        project_key: str,
        story_id: str,
        correlation_id: str,
    ) -> ReadModelRouteResponse:
        project = self.project_repository.get(project_key)
        if project is None:
            return self._not_found(correlation_id)
        story = self.story_service.get_story(story_id)
        if story is None:
            return self._story_not_found(story_id, correlation_id)
        # project_key scope check (FK-73 §73.5, AC7)
        if story.project_key != project_key:
            return self._story_not_found(story_id, correlation_id)
        links = self.are_link_repository.list_by_story(story_id)

        # FK-40 §40.5b.6 / ERROR 2 fix: resolve AreClient per project config.
        # When links exist and ARE is not configured -> FAIL-CLOSED (503).
        # The ARE HTTP transport is the only allowed fake boundary (AC10).
        coverage_verdict = None
        evidence_items = None
        if links:
            are_client = self._resolve_are_client(project_key)
            if are_client is None:
                # Links exist but ARE is not configured for this project.
                # FAIL-CLOSED: returning 'linked' would hide missing coverage.
                return bc_error_response(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    error_code="are_unavailable",
                    message="ARE coverage service not configured for this project",
                    correlation_id=correlation_id,
                )
            try:
                coverage_verdict = are_client.check_gate(story_id)
                evidence_items = are_client.list_evidence(story_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ARE check_gate/list_evidence unavailable for story %r: %s",
                    story_id,
                    exc,
                )
                return bc_error_response(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    error_code="are_unavailable",
                    message="ARE coverage service unavailable",
                    correlation_id=correlation_id,
                )

        evidence = build_are_evidence(
            story_id, project_key, links, coverage_verdict, evidence_items
        )
        return bc_json_response(
            HTTPStatus.OK,
            {"story_are_evidence": evidence.model_dump(mode="json")},
            correlation_id=correlation_id,
        )
