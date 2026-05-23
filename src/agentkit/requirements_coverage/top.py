"""RequirementsCoverage — top-surface for the requirements-coverage BC.

Implements the four ARE dock-points (FK-40 §40.5.1-§40.5.4) and the
activation check (FK-40 §40.2).  When ``features.are`` is disabled,
every method returns a SKIPPED result without error.  When ARE is
enabled but no ``AreClient`` is provided, ``AreConfigurationError``
is raised.  When both are present the dock-point body raises
``AreCapabilityNotImplementedError`` as a contract slot until the
follow-up stories implement the real logic (THEME-009).
"""

from __future__ import annotations

# Avoid a hard import cycle: PipelineConfig imports Features; top.py only
# reads the .features.are attribute, so a TYPE_CHECKING-guarded import is
# sufficient for the constructor type annotation.
from typing import TYPE_CHECKING

from agentkit.requirements_coverage.contract import (
    AreDockpointStatus,
    AreEvidence,
    ContextLoadResult,
    CoverageVerdict,
    EvidenceSubmitResult,
    LinkResult,
)
from agentkit.requirements_coverage.errors import (
    AreCapabilityNotImplementedError,
    AreConfigurationError,
)

if TYPE_CHECKING:
    from agentkit.config.models import PipelineConfig
    from agentkit.requirements_coverage.are_client import AreClient


_MSG_CLIENT_MISSING = "features.are=True but AreClient missing"


class RequirementsCoverage:
    """Top-surface for the requirements-and-scope-coverage BC (FK-40).

    Provides the four ARE dock-points and an activation check.

    Behaviour matrix (AK6 / FAIL CLOSED):

    * ``features.are`` is ``False`` (any client value) → methods return a
      SKIPPED result without error.
    * ``features.are`` is ``True`` and no ``AreClient`` is provided →
      ``AreConfigurationError`` is raised (misconfigured runtime).
    * ``features.are`` is ``True`` and an ``AreClient`` is provided →
      ``AreCapabilityNotImplementedError`` is raised as a contract slot
      until the follow-up stories implement the real logic (THEME-009).

    Args:
        are_client: REST client for the Agent Requirements Engine.
            Pass ``None`` when ARE is not configured.
        pipeline_config: The project's pipeline configuration; the
            ``features.are`` flag controls activation.
    """

    def __init__(
        self,
        are_client: AreClient | None,
        pipeline_config: PipelineConfig,
    ) -> None:
        self._are_client = are_client
        self._pipeline_config = pipeline_config

    @property
    def is_enabled(self) -> bool:
        """Return ``True`` when ARE is activated by configuration.

        Reflects ``pipeline_config.features.are`` only.  The presence of
        an ``AreClient`` is a separate fail-closed precondition checked
        per dock-point method: when ARE is enabled but no client is set,
        the methods raise ``AreConfigurationError`` (AK6, FAIL CLOSED).

        Returns:
            ``True`` iff ``pipeline_config.features.are is True``.
        """
        return self._pipeline_config.features.are is True

    def link_requirements(self, story_id: str, project_key: str) -> LinkResult:
        """Dock-point 1: link ARE requirements to a story (FK-40 §40.5.1).

        Args:
            story_id: AK3-internal story identifier.
            project_key: Target project key.

        Returns:
            ``LinkResult`` with ``status=SKIPPED`` when ARE is disabled.

        Raises:
            AreConfigurationError: When ARE is enabled but no client is set.
            AreCapabilityNotImplementedError: When ARE is enabled and a
                client is set (contract slot — follow-up story required).
        """
        if not self.is_enabled:
            return LinkResult(status=AreDockpointStatus.SKIPPED, reason="feature_disabled")
        if self._are_client is None:
            raise AreConfigurationError(_MSG_CLIENT_MISSING)
        del story_id, project_key
        raise AreCapabilityNotImplementedError(
            "link_requirements full body in follow-up story"
        )

    def load_context(self, story_id: str, project_key: str, run_id: str) -> ContextLoadResult:
        """Dock-point 2: load ARE context for a story (FK-40 §40.5.2).

        Args:
            story_id: AK3-internal story identifier.
            project_key: Target project key.
            run_id: Current pipeline run identifier.

        Returns:
            ``ContextLoadResult`` with ``status=SKIPPED`` when ARE is disabled.

        Raises:
            AreConfigurationError: When ARE is enabled but no client is set.
            AreCapabilityNotImplementedError: When ARE is enabled and a
                client is set (contract slot — follow-up story required).
        """
        if not self.is_enabled:
            return ContextLoadResult(status=AreDockpointStatus.SKIPPED, are_bundle_ref=None)
        if self._are_client is None:
            raise AreConfigurationError(_MSG_CLIENT_MISSING)
        del story_id, project_key, run_id
        raise AreCapabilityNotImplementedError(
            "load_context full body in follow-up story"
        )

    def submit_evidence(self, story_id: str, evidence: AreEvidence) -> EvidenceSubmitResult:
        """Dock-point 3: submit evidence for an ARE requirement (FK-40 §40.5.3).

        Args:
            story_id: AK3-internal story identifier.
            evidence: The evidence to submit.

        Returns:
            ``EvidenceSubmitResult`` with ``status=SKIPPED`` when ARE is disabled.

        Raises:
            AreConfigurationError: When ARE is enabled but no client is set.
            AreCapabilityNotImplementedError: When ARE is enabled and a
                client is set (contract slot — follow-up story required).
        """
        if not self.is_enabled:
            return EvidenceSubmitResult(status=AreDockpointStatus.SKIPPED)
        if self._are_client is None:
            raise AreConfigurationError(_MSG_CLIENT_MISSING)
        del story_id, evidence
        raise AreCapabilityNotImplementedError(
            "submit_evidence full body in follow-up story"
        )

    def check_gate(self, story_id: str, project_key: str) -> CoverageVerdict:
        """Dock-point 4: check the ARE gate for a story (FK-40 §40.5.4).

        Args:
            story_id: AK3-internal story identifier.
            project_key: Target project key.

        Returns:
            ``CoverageVerdict`` with ``status=SKIPPED`` when ARE is disabled.

        Raises:
            AreConfigurationError: When ARE is enabled but no client is set.
            AreCapabilityNotImplementedError: When ARE is enabled and a
                client is set (contract slot — follow-up story required).
                In the follow-up story this will become
                ``CoverageVerdict(status=FAIL, reason="are_gate_unavailable")``
                once Layer-1 is wired (THEME-009 / AG3-042).
        """
        if not self.is_enabled:
            return CoverageVerdict(status=AreDockpointStatus.SKIPPED, verdict=None)
        if self._are_client is None:
            raise AreConfigurationError(_MSG_CLIENT_MISSING)
        del story_id, project_key
        raise AreCapabilityNotImplementedError(
            "check_gate full body in follow-up story"
        )
