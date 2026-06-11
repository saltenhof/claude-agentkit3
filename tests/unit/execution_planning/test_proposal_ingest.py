"""PlanningProposal + ingest tests (AC1-AC3).

AC1: ``PlanningProposal`` is typed with all §70.7b mandatory parts incl.
``proposal_revision``/``source_revision``; an invalid/inconsistent proposal is
rejected fail-closed on ingest.
AC2: ingest validates+normalizes+persists into the canonical view; the canonical
plan is provably an AK3 derivation, not the raw agent answer.
AC3: provenance rule -- a statement without provenance/evidence is stored as a
hint, never as hard truth (§70.7a #3).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from agentkit.bootstrap.composition_root import build_planning_projection_accessor
from agentkit.core_types import StoryDependencyKind
from agentkit.execution_planning.audit import PlanningAuditEmitter
from agentkit.execution_planning.persistence.filter import PlanningProjectionFilter
from agentkit.execution_planning.persistence.schema_kind import PlanningSchemaKind
from agentkit.execution_planning.planning_model.metadata import (
    Provenance,
    ProvenanceReliability,
)
from agentkit.execution_planning.planning_model.proposal import (
    PlanningProposal,
    ProposalBlockingCondition,
    ProposalDependencyEdge,
    ProposalGate,
    ProposalStatus,
)
from agentkit.execution_planning.proposal_ingest import (
    ProposalInconsistentError,
    ingest_proposal,
)
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.telemetry.emitters import MemoryEmitter

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.execution_planning.persistence.accessor import (
        PlanningProjectionAccessor,
    )

_PROJECT = "PROJ-ING"


@pytest.fixture(autouse=True)
def sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@pytest.fixture()
def accessor(tmp_path: Path) -> PlanningProjectionAccessor:
    story_dir = tmp_path / "stories" / "AG3-099"
    story_dir.mkdir(parents=True, exist_ok=True)
    return build_planning_projection_accessor(story_dir)


def _proposal(**overrides: object) -> PlanningProposal:
    base: dict[str, object] = {
        "proposal_id": "PR-1",
        "project_key": _PROJECT,
        "producer_principal": "agent:planner",
        "considered_story_ids": ("S1", "S2"),
        "dependency_edges": (
            ProposalDependencyEdge(
                story_id="S2",
                depends_on_story_id="S1",
                kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            ),
        ),
        "proposal_revision": 1,
        "source_revision": 0,
        "submitted_at": datetime.now(UTC),
        "status": ProposalStatus.SUBMITTED,
    }
    base.update(overrides)
    return PlanningProposal(**base)  # type: ignore[arg-type]


def test_proposal_carries_mandatory_versioning_fields() -> None:
    """AC1: the handover contract carries proposal_revision + source_revision."""
    proposal = _proposal(proposal_revision=3, source_revision=2)
    assert proposal.proposal_revision == 3
    assert proposal.source_revision == 2
    assert proposal.considered_story_ids == ("S1", "S2")


def test_proposal_revision_must_be_positive() -> None:
    """AC1: an invalid proposal (revision < 1) is rejected at construction."""
    with pytest.raises(ValidationError):
        _proposal(proposal_revision=0)


def test_proposal_self_edge_rejected() -> None:
    """AC1: a self-referential proposed edge is rejected at construction."""
    with pytest.raises(ValidationError):
        ProposalDependencyEdge(
            story_id="S1",
            depends_on_story_id="S1",
            kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
        )


def test_ingest_roundtrip_persists_canonical_view(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC2: ingest validates+normalizes+persists into the canonical planning view."""
    proposal = _proposal()
    view = ingest_proposal(proposal, accessor=accessor)

    stories = accessor.read_projection(
        PlanningSchemaKind.PLANNED_STORY, PlanningProjectionFilter(project_key=_PROJECT)
    )
    edges = accessor.read_projection(
        PlanningSchemaKind.DEPENDENCY_EDGE,
        PlanningProjectionFilter(project_key=_PROJECT),
    )
    assert {s.story_id for s in stories} == {"S1", "S2"}  # type: ignore[attr-defined]
    assert len(edges) == 1
    assert len(view.dependencies) == 1


def test_canonical_plan_is_derivation_not_raw_answer(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC2: the canonical view is an AK3 derivation, not the raw agent answer.

    The agent submits ``status=SUBMITTED``; the AK3-derived canonical view is
    ``VALIDATED``. Raw status is NOT copied 1:1.
    """
    proposal = _proposal(status=ProposalStatus.SUBMITTED)
    view = ingest_proposal(proposal, accessor=accessor)
    assert proposal.status is ProposalStatus.SUBMITTED
    assert view.proposal_status is ProposalStatus.VALIDATED


def test_inconsistent_proposal_rejected_no_partial_uptake(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC1: an inconsistent proposal is rejected fail-closed with no partial write."""
    proposal = _proposal(
        considered_story_ids=("S1",),
        dependency_edges=(
            ProposalDependencyEdge(
                story_id="S2",  # not in considered set -> inconsistent
                depends_on_story_id="S1",
                kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            ),
        ),
    )
    with pytest.raises(ProposalInconsistentError):
        ingest_proposal(proposal, accessor=accessor)

    # No partial uptake: nothing was persisted.
    stories = accessor.read_projection(
        PlanningSchemaKind.PLANNED_STORY, PlanningProjectionFilter(project_key=_PROJECT)
    )
    assert stories == []


def test_unknown_blocker_kind_rejected(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC1: a blocker with an unknown kind is rejected fail-closed."""
    proposal = _proposal(
        blocking_conditions=(
            ProposalBlockingCondition(
                story_id="S1",
                kind="totally_unknown_kind",
                reason_code="x",
            ),
        ),
    )
    with pytest.raises(ProposalInconsistentError):
        ingest_proposal(proposal, accessor=accessor)


def test_empty_considered_set_rejected(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC1: a proposal with an empty considered-story set fails closed (FK-70 §70.7b)."""
    proposal = _proposal(considered_story_ids=(), dependency_edges=())
    with pytest.raises(ProposalInconsistentError):
        ingest_proposal(proposal, accessor=accessor)


def test_duplicate_dependency_edge_rejected(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC1: two identical proposed edges (same story/dep/kind) fail closed."""
    edge = ProposalDependencyEdge(
        story_id="S2",
        depends_on_story_id="S1",
        kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
    )
    proposal = _proposal(dependency_edges=(edge, edge))
    with pytest.raises(ProposalInconsistentError):
        ingest_proposal(proposal, accessor=accessor)


def test_gate_outside_considered_set_rejected(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC1: a gate referencing a story outside the considered set fails closed."""
    proposal = _proposal(
        gates=(
            ProposalGate(
                story_id="S99",  # not in considered set
                gate_id="G1",
                gate_kind="human",
                reason_code="uat",
            ),
        ),
    )
    with pytest.raises(ProposalInconsistentError):
        ingest_proposal(proposal, accessor=accessor)


def test_blocker_outside_considered_set_rejected(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC1: a blocking condition for a story outside the considered set fails closed."""
    proposal = _proposal(
        blocking_conditions=(
            ProposalBlockingCondition(
                story_id="S99",  # not in considered set
                kind="blocked_external",
                reason_code="x",
            ),
        ),
    )
    with pytest.raises(ProposalInconsistentError):
        ingest_proposal(proposal, accessor=accessor)


def test_valid_blocking_condition_persisted(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC2: a valid blocking condition is normalized and persisted to the view.

    Proves the blocking-condition persistence leg of ingest (the loop that writes
    each ``BlockingConditionRecord`` through the planning write boundary), not only
    the reject path of an invalid blocker.
    """
    proposal = _proposal(
        blocking_conditions=(
            ProposalBlockingCondition(
                story_id="S1",
                kind="blocked_external",
                reason_code="api_unavailable",
                detail="waiting for partner API",
            ),
        ),
    )
    ingest_proposal(proposal, accessor=accessor)

    blockers = accessor.read_projection(
        PlanningSchemaKind.BLOCKING_CONDITION,
        PlanningProjectionFilter(project_key=_PROJECT),
    )
    assert len(blockers) == 1
    assert blockers[0].story_id == "S1"  # type: ignore[attr-defined]
    assert blockers[0].reason_code == "api_unavailable"  # type: ignore[attr-defined]


def _metadata_for(view: object, story_id: str) -> object:
    return next(
        m
        for m in view.metadata_by_story  # type: ignore[attr-defined]
        if m.story_id == story_id
    )


def test_provenance_rule_hint_without_evidence_not_hard(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC3: a statement without provenance evidence is a hint, not hard.

    The rule must hold for BOTH truths: the persisted ``dependency_edge`` flag
    AND the canonical ``PlanningMetadata`` returned in the planning view. A
    no-provenance edge must NOT enter ``hard_dependency_ids`` -- it stays a hint
    in ``soft_dependency_ids`` (regression for the §70.7a #3 bypass where the
    canonical metadata silently promoted every edge to hard).
    """
    proposal = _proposal(
        dependency_edges=(
            ProposalDependencyEdge(
                story_id="S2",
                depends_on_story_id="S1",
                kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
                provenance=None,  # no provenance -> hint
            ),
        ),
    )
    view = ingest_proposal(proposal, accessor=accessor)

    # Persisted edge flag.
    edges = accessor.read_projection(
        PlanningSchemaKind.DEPENDENCY_EDGE,
        PlanningProjectionFilter(project_key=_PROJECT),
    )
    assert edges[0].is_hard_truth is False  # type: ignore[attr-defined]

    # Canonical metadata: NOT a hard dependency, kept as a soft hint.
    metadata = _metadata_for(view, "S2")
    assert metadata.hard_dependency_ids == ()  # type: ignore[attr-defined]
    assert metadata.soft_dependency_ids == ("S1",)  # type: ignore[attr-defined]


def test_provenance_rule_evidence_backed_is_hard(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC3: an evidence-backed statement is promoted to hard truth.

    Holds for both the persisted edge flag and the canonical metadata: an
    evidence-backed edge enters ``hard_dependency_ids`` and not the soft set.
    """
    proposal = _proposal(
        dependency_edges=(
            ProposalDependencyEdge(
                story_id="S2",
                depends_on_story_id="S1",
                kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
                provenance=Provenance(
                    producer_principal="agent:planner",
                    evidence_refs=("commit:abc123",),
                    reliability=ProvenanceReliability.CORROBORATED,
                ),
            ),
        ),
    )
    view = ingest_proposal(proposal, accessor=accessor)

    edges = accessor.read_projection(
        PlanningSchemaKind.DEPENDENCY_EDGE,
        PlanningProjectionFilter(project_key=_PROJECT),
    )
    assert edges[0].is_hard_truth is True  # type: ignore[attr-defined]

    metadata = _metadata_for(view, "S2")
    assert metadata.hard_dependency_ids == ("S1",)  # type: ignore[attr-defined]
    assert metadata.soft_dependency_ids == ()  # type: ignore[attr-defined]


def test_provenance_rule_mixed_edges_split_hard_and_soft(
    accessor: PlanningProjectionAccessor,
) -> None:
    """AC3: with mixed edges, only evidence-backed ones are hard in the metadata.

    One story has two predecessor edges: one evidence-backed (hard) and one
    without provenance (hint). The canonical metadata must keep them in distinct
    buckets, consistent with the persisted ``is_hard_truth`` flags.
    """
    proposal = _proposal(
        considered_story_ids=("S1", "S2", "S3"),
        dependency_edges=(
            ProposalDependencyEdge(
                story_id="S3",
                depends_on_story_id="S1",
                kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
                provenance=Provenance(
                    producer_principal="agent:planner",
                    evidence_refs=("commit:abc123",),
                ),
            ),
            ProposalDependencyEdge(
                story_id="S3",
                depends_on_story_id="S2",
                kind=StoryDependencyKind.SERIAL_EXECUTION_CONSTRAINT,
                provenance=None,
            ),
        ),
    )
    view = ingest_proposal(proposal, accessor=accessor)
    metadata = _metadata_for(view, "S3")
    assert metadata.hard_dependency_ids == ("S1",)  # type: ignore[attr-defined]
    assert metadata.soft_dependency_ids == ("S2",)  # type: ignore[attr-defined]


def test_ingest_emits_dependency_recorded_audit(
    accessor: PlanningProjectionAccessor,
) -> None:
    """Ingest emits ``dependency_recorded`` per edge over the generic emitter."""
    emitter = MemoryEmitter()
    audit = PlanningAuditEmitter(emitter)
    proposal = _proposal(
        gates=(
            ProposalGate(
                story_id="S1",
                gate_id="G1",
                gate_kind="human",
                reason_code="uat",
            ),
        ),
    )
    ingest_proposal(proposal, accessor=accessor, audit=audit)
    types = [event.event_type.value for event in emitter.all_events]
    assert "dependency_recorded" in types
