"""Unit tests for the reachable reconcile-runtime factory (AG3-114 / AG3-241).

The agent-facing create path runs the REAL fail-closed VectorDB reconciliation
to PRODUCE the self-validating evidence before ``POST /v1/stories`` — never a
hand-built / skipped evidence. This module owns the wiring of that runtime from
the target-project config. These tests pin the fail-closed behaviour:

* a missing ``vectordb`` host/port (the VectorDB is mandatory infrastructure)
  fails closed with ``VectorDbUnavailableError`` — no creation without the
  reconciliation runtime.
* the stage-2 evaluator is the REST adjudicator when a ``project_root`` exists
  (AG3-241: the assessment runs in the core), and the fail-closed evaluator when
  none does. Either way an above-threshold conflict that needs adjudication is
  BLOCKED with a TRUTHFUL ``ConflictAdjudicationUnavailableError`` (NOT a
  VectorDB outage), never silently passed.
"""

from __future__ import annotations

import pytest

from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    VectorDbConfig,
)
from agentkit.backend.exceptions import ConflictAdjudicationUnavailableError
from agentkit.backend.story_creation.runtime_factory import (
    FailClosedConflictEvaluator,
    build_create_time_conflict_evaluator,
    build_story_creation_reconciler,
)
from agentkit.backend.story_creation.vectordb_reconciliation import (
    ConflictEvaluatorPort,
)
from agentkit.integration_clients.vectordb import VectorDbError, VectorDbUnavailableError
from agentkit_wire.verify_system import (
    ConflictCandidate,
    StoryConflictAssessmentRequest,
)


def _config(*, vectordb: VectorDbConfig | None) -> ProjectConfig:
    return ProjectConfig(
        project_key="ak3",
        project_name="AgentKit 3",
        repositories=[RepositoryConfig(name="ak3-backend", path="services/api")],
        story_types=["concept"],
        pipeline=PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            vectordb=vectordb,
        ),  # type: ignore[call-arg]
    )


def _request() -> StoryConflictAssessmentRequest:
    return StoryConflictAssessmentRequest(
        story_id="DRAFT-AG3-999",
        story_description="Add retry/backoff to the broker adapter.",
        candidates=(ConflictCandidate(story_id="AG3-012", score=0.94),),
    )


def test_factory_fails_closed_without_vectordb_config() -> None:
    """No vectordb stanza => fail-closed (the VectorDB is mandatory, FK-13 §13.2)."""
    with pytest.raises(VectorDbUnavailableError, match="mandatory"):
        build_story_creation_reconciler(project_config=_config(vectordb=None))


def test_factory_fails_closed_without_an_http_endpoint() -> None:
    """A vectordb config without an endpoint still fails closed (no silent skip).

    PO decision D-2 removed host/port; the endpoint is now the only source, so the
    fail-closed condition moved to it.
    """
    with pytest.raises(VectorDbUnavailableError):
        build_story_creation_reconciler(
            project_config=_config(
                vectordb=VectorDbConfig(weaviate_http_endpoint=None),
            )
        )


def test_fail_closed_conflict_evaluator_blocks_unadjudicated_conflict() -> None:
    """The fallback stage-2 evaluator BLOCKS fail-closed (no reachable core).

    An above-threshold similarity conflict that reaches stage 2 cannot be silently
    passed; with no Project-Edge client wired it raises the TRUTHFUL
    ``ConflictAdjudicationUnavailableError`` (FK-21 §21.4.3 / NO ERROR BYPASSING).
    """
    evaluator = FailClosedConflictEvaluator()
    with pytest.raises(ConflictAdjudicationUnavailableError, match="BLOCKED fail-"):
        evaluator.assess(_request())


def test_fail_closed_conflict_evaluator_is_not_a_vectordb_error() -> None:
    """The conflict-adjudication signal must NOT masquerade as a VectorDB outage.

    The VectorDB is healthy when stage 2 is reached; mislabelling the missing
    adjudication owner as ``vectordb_unavailable`` was the reviewer's finding #3.
    """
    evaluator = FailClosedConflictEvaluator()
    with pytest.raises(ConflictAdjudicationUnavailableError) as exc_info:
        evaluator.assess(_request())
    assert not isinstance(exc_info.value, VectorDbError)


def test_fail_closed_evaluator_satisfies_the_port_it_substitutes_for() -> None:
    """The fallback fills the SAME ``ConflictEvaluatorPort`` slot as the real one.

    A fallback with a different surface would fail late, at the first conflict,
    instead of at wiring time.
    """
    assert isinstance(FailClosedConflictEvaluator(), ConflictEvaluatorPort)


# -- AG3-241: stage 2 is ASKED FOR over /v1, never run in this process -------


def test_no_project_root_means_no_adjudicator_can_be_built() -> None:
    """Without a project root there is no client, so there is no adjudicator.

    The factory answers ``None`` here and the caller substitutes the truthful
    fail-closed evaluator — it does not invent a local verdict.
    """
    assert (
        build_create_time_conflict_evaluator(
            _config(vectordb=None), project_root=None
        )
        is None
    )
