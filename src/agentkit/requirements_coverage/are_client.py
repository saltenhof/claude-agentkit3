"""AreClient — REST adapter skeleton for the Agent Requirements Engine.

BC-internal sub of ``agentkit.requirements_coverage`` (FK-40 §40.4).
The full HTTP implementation is deferred to follow-up stories; every
method raises ``NotImplementedError`` with an explicit follow-up reference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.requirements_coverage.contract import (
        AreContext,
        AreRequirement,
        CoverageVerdict,
        EvidenceSubmitResult,
        EvidenceType,
    )


class AreClient:
    """REST client stub for the ARE API (FK-40 §40.4).

    Communicates with the external Agent Requirements Engine REST API.
    All method bodies are deferred to follow-up implementation stories.

    Args:
        base_url: Base URL of the ARE REST API.
        auth_token: Optional bearer token for authenticated requests.
    """

    def __init__(self, base_url: str, auth_token: str | None = None) -> None:
        self._base_url = base_url
        self._auth_token = auth_token

    def list_requirements(self, story_id: str, scope: str) -> list[AreRequirement]:
        """List requirements for a story in a given scope (dock-point 1).

        Args:
            story_id: AK3-internal story identifier.
            scope: ARE scope string derived from repo or module mapping.

        Returns:
            List of ``AreRequirement`` objects matching the scope.

        Raises:
            NotImplementedError: Always — full body is a follow-up story.
        """
        raise NotImplementedError("AreClient.list_requirements is follow-up")

    def get_recurring(self, scope: str, story_type: str) -> list[AreRequirement]:
        """Get recurring mandatory requirements for a scope and story type (dock-point 1).

        Args:
            scope: ARE scope string.
            story_type: AK3 story type (e.g. ``"implementation"``).

        Returns:
            List of recurring ``AreRequirement`` objects.

        Raises:
            NotImplementedError: Always — full body is a follow-up story.
        """
        raise NotImplementedError("AreClient.get_recurring is follow-up")

    def load_context(self, story_id: str) -> AreContext:
        """Load must-cover requirements context for a story (dock-point 2).

        Args:
            story_id: AK3-internal story identifier.

        Returns:
            ``AreContext`` with the fetched requirements.

        Raises:
            NotImplementedError: Always — full body is a follow-up story.
        """
        raise NotImplementedError("AreClient.load_context is follow-up")

    def submit_evidence(
        self,
        story_id: str,
        requirement_id: str,
        evidence_type: EvidenceType,
        evidence_ref: str,
    ) -> EvidenceSubmitResult:
        """Submit evidence for a requirement (dock-point 3).

        Args:
            story_id: AK3-internal story identifier.
            requirement_id: ARE-side requirement identifier.
            evidence_type: Classification of the evidence.
            evidence_ref: Concrete reference (test locator, commit SHA,
                artifact path, or free text).

        Returns:
            ``EvidenceSubmitResult`` confirming the submission.

        Raises:
            NotImplementedError: Always — full body is a follow-up story.
        """
        raise NotImplementedError("AreClient.submit_evidence is follow-up")

    def check_gate(self, story_id: str) -> CoverageVerdict:
        """Check the ARE gate for a story (dock-point 4).

        Args:
            story_id: AK3-internal story identifier.

        Returns:
            ``CoverageVerdict`` with PASS or FAIL and coverage details.

        Raises:
            NotImplementedError: Always — full body is a follow-up story.
        """
        raise NotImplementedError("AreClient.check_gate is follow-up")
