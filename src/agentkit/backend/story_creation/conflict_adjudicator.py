"""Create-time conflict adjudication, asked for over ``/v1`` (FK-21 §21.4.1).

FK-21 §21.4.1 Schritt 3 gates story creation with an LLM conflict assessment.
Until AG3-241 this process ran it: it held ``HubLlmClient``, the shared
``StructuredEvaluator`` and a prompt materializer and evaluated the very story
being created. That is the arrangement ``CLAUDE.md`` §WORKFLOW- UND
STATE-DISZIPLIN forbids -- the judged must not own the judge -- and over two
machines it is not merely wrong but impossible.

What remains here is the *asking*. Stage 1 (the Weaviate similarity search) stays
local because the candidates can only be found where the index is reachable; the
verdict comes from
``POST /v1/projects/{project_key}/story-conflict-assessments``.

Fail-closed (FK-21 §21.4.3): an unreachable core, a rejected request or an
unreadable answer raises :class:`CreateTimeConflictAdjudicationError`. There is
no local verdict to fall back to and none is invented -- no dummy verdict, no
"PASS when in doubt". The error stays deliberately distinct from
``VectorDbError``: at this point the VectorDB is healthy, it just returned the
candidates. The tool contract maps it to ``conflict_adjudication_unavailable``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit_wire.verify_system import (
    ConflictCandidate,
    StoryConflictAssessmentRequest,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.harness_client.projectedge.client import ProjectEdgeClient
    from agentkit_wire.verify_system import StoryConflictAssessmentResponse


class CreateTimeConflictAdjudicationError(Exception):
    """Fail-closed: the create-time conflict assessment could not be obtained.

    Raised when the core is unreachable, rejects the assessment request, or
    answers with something that is not a verdict. It is DELIBERATELY a distinct
    type from
    :class:`~agentkit.integration_clients.vectordb.VectorDbError`: the VectorDB is
    healthy (stage-1 similarity already returned the candidates that triggered
    stage 2); only the create-time assessment is unavailable. Story creation
    blocks (FK-21 §21.4.3 / NO ERROR BYPASSING) rather than passing an
    unadjudicated conflict. It carries no dummy verdict.
    """


class RestConflictAdjudicator:
    """Obtain the create-time conflict verdict from the core over ``/v1``.

    Attributes:
        _client: The official Project-Edge client (the ONLY way out of this
            process to the core).
        _project_key: The project scope of the assessment.
    """

    def __init__(self, client: ProjectEdgeClient, *, project_key: str) -> None:
        """Initialise the adjudicator over the official client.

        Args:
            client: The Project-Edge client bound to this project's core.
            project_key: The project the draft story belongs to.
        """
        self._client = client
        self._project_key = project_key

    def assess(
        self, request: StoryConflictAssessmentRequest
    ) -> StoryConflictAssessmentResponse:
        """Ask the core for the binary conflict verdict.

        Args:
            request: The draft story plus its above-threshold candidates.

        Returns:
            The core's binary verdict.

        Raises:
            CreateTimeConflictAdjudicationError: When the verdict cannot be
                obtained -- fail-closed, truthful and distinguishable from a
                VectorDB outage.
        """
        try:
            return self._client.assess_story_conflict(
                project_key=self._project_key, request=request
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise CreateTimeConflictAdjudicationError(
                "create-time conflict adjudication (FK-21 §21.4.1 Schritt 3) could "
                "not run: the core did not return a usable verdict. The VectorDB is "
                "healthy (stage-1 similarity already returned the candidates); only "
                "the assessment failed. Story creation is BLOCKED fail-closed "
                f"(FK-21 §21.4.3) -- no dummy verdict. Cause: {exc}"
            ) from exc


def build_assessment_request(
    *,
    story_id: str,
    story_description: str,
    candidates: Sequence[ConflictCandidate],
) -> StoryConflictAssessmentRequest:
    """Build the wire request of one create-time conflict assessment.

    Args:
        story_id: The draft display-id (the search scope, not a persisted id).
        story_description: The new story description.
        candidates: The above-threshold similarity candidates.

    Returns:
        The validated wire request.
    """
    return StoryConflictAssessmentRequest(
        story_id=story_id,
        story_description=story_description,
        candidates=tuple(candidates),
    )


__all__ = [
    "ConflictCandidate",
    "CreateTimeConflictAdjudicationError",
    "RestConflictAdjudicator",
    "build_assessment_request",
]
