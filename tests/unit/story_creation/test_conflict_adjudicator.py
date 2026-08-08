"""Unit tests for the EDGE half of the create-time conflict assessment (AG3-241).

Since AG3-241 this module is the *asking*, not the adjudication: the verdict is
produced by the core behind
``POST /v1/projects/{project_key}/story-conflict-assessments`` and this process
only carries the question there and the answer back. The adjudication itself is
tested where it now lives --
``tests/unit/verify_system/llm_evaluator/test_create_scope_conflict.py``.

Two properties matter here and nothing else:

* the core's verdict is what comes out -- the edge neither re-derives nor
  softens it;
* a core that cannot answer produces a fail-closed
  :class:`CreateTimeConflictAdjudicationError` and NEVER a ``PASS``.

The only fake is the network boundary to the core (the ``ProjectEdgeClient``
seam), which is the CLAUDE.md mocks-exception.
"""

from __future__ import annotations

import pytest

from agentkit.backend.story_creation.conflict_adjudicator import (
    CreateTimeConflictAdjudicationError,
    RestConflictAdjudicator,
    build_assessment_request,
)
from agentkit.integration_clients.vectordb import VectorDbError
from agentkit_wire.verify_system import (
    ConflictCandidate,
    ConflictVerdict,
    StoryConflictAssessmentRequest,
    StoryConflictAssessmentResponse,
)


class _FakeClient:
    """Network-boundary double for the ONE call out of this process.

    Either answers with a canned verdict or raises the failure the real
    transport raises when the core cannot be reached / does not answer usably.
    """

    def __init__(
        self,
        *,
        verdict: ConflictVerdict | None = None,
        error: Exception | None = None,
    ) -> None:
        self._verdict = verdict
        self._error = error
        self.calls: list[tuple[str, StoryConflictAssessmentRequest]] = []

    def assess_story_conflict(
        self, *, project_key: str, request: StoryConflictAssessmentRequest
    ) -> StoryConflictAssessmentResponse:
        self.calls.append((project_key, request))
        if self._error is not None:
            raise self._error
        assert self._verdict is not None
        return StoryConflictAssessmentResponse(verdict=self._verdict)


def _request(story_id: str = "DRAFT-AG3-999") -> StoryConflictAssessmentRequest:
    return build_assessment_request(
        story_id=story_id,
        story_description="Add a retry/backoff path to the broker adapter.",
        candidates=[
            ConflictCandidate(
                story_id="AG3-012",
                score=0.94,
                title="Broker adapter resilience",
                snippet="adds retry",
            )
        ],
    )


# -- the core's verdict is the verdict --------------------------------------


@pytest.mark.parametrize("verdict", [ConflictVerdict.PASS, ConflictVerdict.FAIL])
def test_returns_the_cores_verdict_unchanged(verdict: ConflictVerdict) -> None:
    """The edge relays the binary verdict; it neither re-derives nor softens it."""
    client = _FakeClient(verdict=verdict)
    adjudicator = RestConflictAdjudicator(client, project_key="ak3")  # type: ignore[arg-type]

    assert adjudicator.assess(_request()).verdict is verdict


def test_scopes_the_call_to_its_project_and_sends_the_request_unchanged() -> None:
    """The project scope is the adjudicator's, not the caller's, and the
    question travels exactly as it was built."""
    client = _FakeClient(verdict=ConflictVerdict.PASS)
    adjudicator = RestConflictAdjudicator(client, project_key="ak3")  # type: ignore[arg-type]
    request = _request("DRAFT-X")

    adjudicator.assess(request)

    assert len(client.calls) == 1
    project_key, sent = client.calls[0]
    assert project_key == "ak3"
    assert sent == request


# -- an unreachable core BLOCKS; it never becomes a PASS --------------------


@pytest.mark.parametrize(
    "error",
    [
        OSError("connection refused"),
        RuntimeError("core answered 503 story_conflict_assessment_unavailable"),
        ValueError("response body is not a verdict"),
    ],
    ids=["unreachable", "core-unavailable", "unreadable-answer"],
)
def test_core_failure_fails_closed_and_never_passes(error: Exception) -> None:
    """Any failure to OBTAIN the verdict blocks the create -- no dummy verdict.

    ``CreateTimeConflictAdjudicationError`` carries no verdict at all, which is
    the point: there is no local substitute for the core's judgement and none is
    invented.
    """
    client = _FakeClient(error=error)
    adjudicator = RestConflictAdjudicator(client, project_key="ak3")  # type: ignore[arg-type]

    with pytest.raises(CreateTimeConflictAdjudicationError) as exc_info:
        adjudicator.assess(_request())

    raised = exc_info.value
    assert not hasattr(raised, "verdict")
    assert raised.__cause__ is error


def test_core_failure_is_not_a_vectordb_outage() -> None:
    """The failure stays truthfully distinguishable from a VectorDB outage.

    Stage 1 already succeeded -- it produced the candidates that triggered
    stage 2 -- so labelling this a VectorDB outage would send an operator to the
    wrong system.
    """
    client = _FakeClient(error=OSError("connection refused"))
    adjudicator = RestConflictAdjudicator(client, project_key="ak3")  # type: ignore[arg-type]

    with pytest.raises(CreateTimeConflictAdjudicationError) as exc_info:
        adjudicator.assess(_request())

    assert not isinstance(exc_info.value, VectorDbError)
    message = str(exc_info.value)
    assert "VectorDB is healthy" in message
    assert "BLOCKED fail-closed" in message


def test_the_adjudication_is_not_performed_in_this_process() -> None:
    """The edge module carries no evaluator vocabulary any more (AG3-241).

    The whole reason for the move is that the process creating the story must
    not run the evaluation that judges it. A re-appearing evaluator symbol here
    would restore exactly that arrangement, so it is asserted against.
    """
    from agentkit.backend.story_creation import conflict_adjudicator

    for forbidden in (
        "CreateTimeConflictAdjudicator",
        "CreateScopePromptMaterializer",
        "StructuredEvaluator",
        "HubLlmClient",
    ):
        assert not hasattr(conflict_adjudicator, forbidden), (
            f"{forbidden} is back in the edge module; the create-time assessment "
            "must run in the core (AG3-241)."
        )
