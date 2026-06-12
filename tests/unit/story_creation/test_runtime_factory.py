"""Unit tests for the reachable reconcile-runtime factory (AG3-114, FK-21 §21.4).

The agent-facing create path runs the REAL fail-closed VectorDB reconciliation
to PRODUCE the self-validating evidence before ``POST /v1/stories`` — never a
hand-built / skipped evidence. This module owns the wiring of that runtime from
the target-project config. These tests pin the fail-closed behaviour:

* a missing ``vectordb`` host/port (the VectorDB is mandatory infrastructure)
  fails closed with ``VectorDbUnavailableError`` — no creation without the
  reconciliation runtime.
* the default stage-2 evaluator is fail-closed: there is no create-time LLM
  owner, so an above-threshold conflict that needs adjudication is BLOCKED with a
  TRUTHFUL ``ConflictAdjudicationUnavailableError`` (NOT a VectorDB outage), not
  silently passed.
"""

from __future__ import annotations

import pytest

from agentkit.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    VectorDbConfig,
)
from agentkit.exceptions import ConflictAdjudicationUnavailableError
from agentkit.integrations.vectordb import VectorDbError, VectorDbUnavailableError
from agentkit.story_creation.runtime_factory import (
    FailClosedConflictEvaluator,
    build_story_creation_reconciler,
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


def test_factory_fails_closed_without_vectordb_config() -> None:
    """No vectordb stanza => fail-closed (the VectorDB is mandatory, FK-13 §13.2)."""
    with pytest.raises(VectorDbUnavailableError, match="mandatory"):
        build_story_creation_reconciler(project_config=_config(vectordb=None))


def test_factory_fails_closed_without_host_or_port() -> None:
    """A vectordb config missing host/port still fails closed (no silent skip)."""
    with pytest.raises(VectorDbUnavailableError):
        build_story_creation_reconciler(
            project_config=_config(
                vectordb=VectorDbConfig(host=None, port=None),
            )
        )


def test_fail_closed_conflict_evaluator_blocks_unadjudicated_conflict() -> None:
    """The default stage-2 evaluator BLOCKS fail-closed (no create-time LLM owner).

    An above-threshold similarity conflict that reaches stage 2 cannot be silently
    passed; with no create-time adjudicator wired it raises the TRUTHFUL
    ``ConflictAdjudicationUnavailableError`` (FK-21 §21.4.3 / NO ERROR BYPASSING).
    """
    evaluator = FailClosedConflictEvaluator()
    with pytest.raises(ConflictAdjudicationUnavailableError, match="BLOCKED fail-"):
        evaluator.evaluate(
            role=None,  # type: ignore[arg-type]
            bundle=None,  # type: ignore[arg-type]
            previous_findings=None,
            qa_cycle_round=0,
        )


def test_fail_closed_conflict_evaluator_is_not_a_vectordb_error() -> None:
    """The conflict-adjudication signal must NOT masquerade as a VectorDB outage.

    The VectorDB is healthy when stage 2 is reached; mislabelling the missing
    adjudication owner as ``vectordb_unavailable`` was the reviewer's finding #3.
    """
    evaluator = FailClosedConflictEvaluator()
    with pytest.raises(ConflictAdjudicationUnavailableError) as exc_info:
        evaluator.evaluate(
            role=None,  # type: ignore[arg-type]
            bundle=None,  # type: ignore[arg-type]
            previous_findings=None,
            qa_cycle_round=0,
        )
    assert not isinstance(exc_info.value, VectorDbError)
