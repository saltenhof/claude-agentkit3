"""Verify-system HTTP surface of the control plane (FK-91 §91.1a, AG3-241).

Two operations of the capability bounded context ``verify-system`` are reachable
from the developer machine, and both exist for the same reason: the raw
observation is only makeable there, the judgement is only allowed here.

* ``POST /v1/projects/{project_key}/story-conflict-assessments`` -- the create-time
  LLM conflict assessment (FK-21 §21.4.1, step 3). Neither operation mutates
  canonical state, so neither carries an Operation-Ledger ``op_id`` (FK-91 §91.1a
  rule 5; same reasoning as ``POST /v1/auth/login``).
* ``POST /v1/projects/{project_key}/verify-evidence-assemblies`` -- the review
  bundle of one edge-exported evidence checkpoint (FK-28 §28.7.1).

The filesystem anchor is resolved HERE, from the canonical ``project_registry``
(FK-10 §10.2.3 / I3) -- never from a path in the request body. The developer
machine's ``project_root`` is meaningless on the core host, and a request field
that supplied one would make the core's story artefacts addressable from outside.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.control_plane_http import _route_patterns
from agentkit.backend.control_plane_http.responses import (
    HttpResponse,
    _error_response,
    _json_response,
)
from agentkit.backend.exceptions import ConfigError
from agentkit.backend.installer.paths import story_dir as resolve_story_dir
from agentkit.backend.verify_system.evidence.assembler import EvidenceAssemblyError
from agentkit_wire.verify_system import (
    StoryConflictAssessmentRequest,
    VerifyEvidenceAssemblyRequest,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.config.models import ProjectConfig

logger = logging.getLogger(__name__)


def _default_project_root_lookup() -> Callable[[str], Path | None]:
    """Return the composition-root project-root lookup.

    The lookup is composed over the installer writer service, the owner of the
    CP-7 ``project_registry`` record. This module must not read the state backend
    itself: a control-plane HTTP module that bypasses the owner BC's port is an
    architecture-conformance violation (AC001 / AC010).

    Returns:
        The canonical ``project_key -> project_root`` lookup.
    """
    from agentkit.backend.bootstrap.composition_installer import (
        build_project_root_lookup,
    )

    return build_project_root_lookup()


class VerifySystemRoutes:
    """Handlers of the two verify-system ``/v1`` operations.

    Attributes:
        _project_root_lookup: Resolves the core-host project root from the
            canonical project registry.
    """

    def __init__(
        self,
        *,
        project_root_lookup: Callable[[str], Path | None] | None = None,
    ) -> None:
        """Initialise the handlers.

        Args:
            project_root_lookup: Optional seam over the canonical project
                registry; defaults to the composition-root wiring over the owner
                BC's port (this module never reads the state backend itself).
        """
        self._project_root_lookup = project_root_lookup or _default_project_root_lookup()

    def dispatch_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse | None:
        """Dispatch a POST to this surface, or return ``None`` when unmatched.

        Lives here rather than on ``ControlPlaneApplication``: it dispatches to
        this class's own handlers, and every bounded context that hangs routes
        on the application would otherwise grow that class past its size budget
        (Sonar PY_CLASS_MAX_LOC_800). AG3-239 already moved the hook-mediation
        dispatcher for the same reason.
        """
        conflict_match = _route_patterns._PROJECT_STORY_CONFLICT_ASSESSMENTS.match(
            route_path
        )
        if conflict_match is not None:
            return self.handle_story_conflict_assessment(
                project_key=conflict_match.group("project_key"),
                payload=payload,
                correlation_id=correlation_id,
            )
        evidence_match = _route_patterns._PROJECT_VERIFY_EVIDENCE_ASSEMBLIES.match(
            route_path
        )
        if evidence_match is not None:
            return self.handle_evidence_assembly(
                project_key=evidence_match.group("project_key"),
                payload=payload,
                correlation_id=correlation_id,
            )
        return None

    def handle_story_conflict_assessment(
        self,
        *,
        project_key: str,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        """Run one create-time conflict assessment (FK-21 §21.4.1 Schritt 3).

        Args:
            project_key: The project the draft story belongs to.
            payload: The decoded request body.
            correlation_id: The request correlation id.

        Returns:
            ``200`` with the binary verdict, or a stable error response.
        """
        from agentkit.backend.verify_system.llm_evaluator.create_scope_conflict import (
            CreateScopeConflictUnavailableError,
            assess_story_conflict,
        )

        try:
            request = StoryConflictAssessmentRequest.model_validate(payload)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_story_conflict_assessment_payload",
                message="Invalid story-conflict assessment payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        project_root = self._project_root_lookup(project_key)
        if project_root is None:
            return self._project_not_registered(project_key, correlation_id)
        try:
            project_config = self._load_project_config(project_root)
            response = assess_story_conflict(
                request,
                project_config=project_config,
                project_root=project_root,
            )
        except ConfigError as exc:
            logger.warning("Story-conflict assessment config defect: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="story_conflict_assessment_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except CreateScopeConflictUnavailableError as exc:
            # Fail-closed and TRUTHFUL: the VectorDB is healthy (stage 1 produced
            # the candidates); only the assessment could not run. No dummy verdict.
            logger.warning("Story-conflict assessment unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="story_conflict_assessment_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            response.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    def handle_evidence_assembly(
        self,
        *,
        project_key: str,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse:
        """Assemble one review bundle from an evidence checkpoint (FK-28 §28.7.1).

        Args:
            project_key: The project the story belongs to.
            payload: The decoded request body.
            correlation_id: The request correlation id.

        Returns:
            ``200`` with the manifest, or a stable error response.
        """
        from agentkit.backend.verify_system.evidence.assembly_service import (
            assemble_evidence_bundle,
        )

        try:
            request = VerifyEvidenceAssemblyRequest.model_validate(payload)
        except ValidationError as exc:
            return _error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_verify_evidence_assembly_payload",
                message="Invalid verify-evidence assembly payload",
                correlation_id=correlation_id,
                detail=exc.errors(),
            )
        project_root = self._project_root_lookup(project_key)
        if project_root is None:
            return self._project_not_registered(project_key, correlation_id)
        story_dir = resolve_story_dir(project_root, request.story_id)
        try:
            response = assemble_evidence_bundle(request, story_dir=story_dir)
        # `ValidationError` derives from `ValueError`, so naming both would catch
        # the same thing twice (Sonar S5713). `EvidenceAssemblyError` derives
        # from `RuntimeError` and is therefore listed separately.
        except (EvidenceAssemblyError, ValueError) as exc:
            # The checkpoint itself cannot produce a bundle -- a caller defect,
            # not an outage. 422 keeps it distinct from a malformed body (400)
            # and from an unavailable core (503).
            return _error_response(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code="verify_evidence_assembly_rejected",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except OSError as exc:
            logger.warning("Verify-evidence assembly unavailable: %s", exc)
            return _error_response(
                HTTPStatus.SERVICE_UNAVAILABLE,
                error_code="verify_evidence_assembly_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK,
            response.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

    @staticmethod
    def _load_project_config(project_root: Path) -> ProjectConfig:
        """Load the target-project config from the core-host root.

        Args:
            project_root: The registered project root.

        Returns:
            The parsed project config.
        """
        from agentkit.backend.config.loader import load_project_config

        return load_project_config(project_root)

    @staticmethod
    def _project_not_registered(project_key: str, correlation_id: str) -> HttpResponse:
        """Return the stable 404 for an unknown project identity.

        Args:
            project_key: The unresolvable project key.
            correlation_id: The request correlation id.

        Returns:
            The ``404`` response.
        """
        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="project_not_registered",
            message=f"No project registration for {project_key!r}",
            correlation_id=correlation_id,
        )


__all__ = ["VerifySystemRoutes"]
