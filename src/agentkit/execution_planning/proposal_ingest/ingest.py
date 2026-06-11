"""Validate, normalize and persist a PlanningProposal into the canonical view.

FK-70 §70.7b/§70.7c: AK3 validates, normalizes and persists an agent proposal;
the canonical ``ExecutionPlan`` stays an AK3-owned derivation, never the raw
agent answer. This module produces a ``CanonicalPlanningView`` (typed AG3-098
domain objects + per-story ``PlanningMetadata``) and persists each derived
planning family through the BC-9 planning projection write path. The raw agent
fields are NOT copied 1:1 -- they are re-derived into canonical typed objects.

FAIL-CLOSED: an inconsistent proposal is rejected wholesale before any write.
Provenance rule (§70.7a #3): an edge/blocker without provenance evidence is kept
as a hint (``is_hard_truth=False``); only evidence-backed statements become hard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from agentkit.execution_planning.entities import (
    BlockingCondition,
    BlockingConditionKind,
    BlockingConditionProvenance,
    StoryDependency,
)
from agentkit.execution_planning.persistence.records import (
    BlockingConditionRecord,
    DependencyEdgeRecord,
    GateRecord,
    PlannedStoryRecord,
)
from agentkit.execution_planning.persistence.schema_kind import PlanningSchemaKind
from agentkit.execution_planning.planning_model.metadata import (
    GateMetadata,
    PlanningMetadata,
)
from agentkit.execution_planning.planning_model.proposal import ProposalStatus
from agentkit.execution_planning.proposal_ingest.errors import (
    ProposalInconsistentError,
)

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.execution_planning.audit import PlanningAuditEmitter
    from agentkit.execution_planning.persistence.accessor import (
        PlanningProjectionAccessor,
    )
    from agentkit.execution_planning.planning_model.metadata import Provenance
    from agentkit.execution_planning.planning_model.proposal import (
        PlanningProposal,
        ProposalBlockingCondition,
        ProposalDependencyEdge,
    )

__all__ = ["CanonicalPlanningView", "ingest_proposal"]


# Mapping from the proposal's blocker wire-kind onto the canonical AG3-098 enum.
# An unknown kind is a consistency error (FAIL-CLOSED), never a silent default.
def _map_blocking_kind(kind: str) -> BlockingConditionKind:
    try:
        return BlockingConditionKind(kind)
    except ValueError as exc:
        raise ProposalInconsistentError(
            f"Unknown blocking-condition kind {kind!r} in proposal "
            "(FAIL-CLOSED: not in the AG3-098 BlockingConditionKind vocabulary)"
        ) from exc


def _provenance_is_hard(provenance: Provenance | None) -> bool:
    return provenance is not None and provenance.has_evidence


class CanonicalPlanningView(BaseModel):
    """The canonical AK3-derived planning view for one ingested proposal.

    This is the AK3 derivation, NOT the raw proposal: edges/blockers are
    canonical AG3-098 domain objects, per-story metadata is the §70.7a contract,
    and ``proposal_status`` is set to ``VALIDATED`` by ingest (the raw proposal
    arrives ``SUBMITTED``). Hint vs hard-truth is resolved per the provenance
    rule.

    Attributes:
        project_key: Tenant/project scope key.
        proposal_id: Source proposal identity.
        proposal_revision: Source proposal revision.
        source_revision: Source upstream revision.
        proposal_status: Always ``VALIDATED`` for a successfully ingested view.
        dependencies: Canonical AG3-098 ``StoryDependency`` edges.
        blocking_conditions: Canonical AG3-098 ``BlockingCondition`` objects.
        metadata_by_story: Per-story canonical ``PlanningMetadata``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    proposal_id: str
    proposal_revision: int = Field(ge=1)
    source_revision: int = Field(ge=0)
    proposal_status: ProposalStatus
    dependencies: tuple[StoryDependency, ...] = Field(default_factory=tuple)
    blocking_conditions: tuple[BlockingCondition, ...] = Field(default_factory=tuple)
    metadata_by_story: tuple[PlanningMetadata, ...] = Field(default_factory=tuple)


def _validate_consistency(proposal: PlanningProposal) -> None:
    considered = set(proposal.considered_story_ids)
    if not considered:
        raise ProposalInconsistentError(
            "Proposal has an empty considered story set (FK-70 §70.7b)"
        )

    seen_edges: set[tuple[str, str, str]] = set()
    for edge in proposal.dependency_edges:
        if edge.story_id not in considered or edge.depends_on_story_id not in considered:
            raise ProposalInconsistentError(
                "Proposal dependency edge references a story outside the "
                f"considered set: {edge.story_id} -> {edge.depends_on_story_id}"
            )
        key = (edge.story_id, edge.depends_on_story_id, edge.kind.value)
        if key in seen_edges:
            raise ProposalInconsistentError(
                f"Proposal contains a duplicate dependency edge: {key}"
            )
        seen_edges.add(key)

    for blocker in proposal.blocking_conditions:
        if blocker.story_id not in considered:
            raise ProposalInconsistentError(
                "Proposal blocking condition references a story outside the "
                f"considered set: {blocker.story_id}"
            )
    for gate in proposal.gates:
        if gate.story_id not in considered:
            raise ProposalInconsistentError(
                "Proposal gate references a story outside the considered set: "
                f"{gate.story_id}"
            )


def _to_metadata(proposal: PlanningProposal) -> tuple[PlanningMetadata, ...]:
    gates_by_story: dict[str, list[GateMetadata]] = {}
    for gate in proposal.gates:
        gates_by_story.setdefault(gate.story_id, []).append(
            GateMetadata(
                gate_id=gate.gate_id,
                gate_kind=gate.gate_kind,
                reason_code=gate.reason_code,
                is_blocking=gate.is_blocking,
            )
        )

    # Provenance rule (§70.7a #3) applied CONSISTENTLY with the persisted edge
    # flag (``DependencyEdgeRecord.is_hard_truth``): an edge whose OWN provenance
    # carries evidence becomes a canonical hard dependency; an edge without
    # provenance/evidence stays a HINT and lands in ``soft_dependency_ids``, never
    # silently in ``hard_dependency_ids``.
    hard_deps_by_story: dict[str, list[str]] = {}
    soft_deps_by_story: dict[str, list[str]] = {}
    for edge in proposal.dependency_edges:
        bucket = (
            hard_deps_by_story
            if _provenance_is_hard(edge.provenance)
            else soft_deps_by_story
        )
        bucket.setdefault(edge.story_id, []).append(edge.depends_on_story_id)

    metadata: list[PlanningMetadata] = []
    for story_id in proposal.considered_story_ids:
        metadata.append(
            PlanningMetadata(
                project_key=proposal.project_key,
                story_id=story_id,
                hard_dependency_ids=tuple(hard_deps_by_story.get(story_id, ())),
                soft_dependency_ids=tuple(soft_deps_by_story.get(story_id, ())),
                gates=tuple(gates_by_story.get(story_id, ())),
                provenance=proposal.provenance,
            )
        )
    return tuple(metadata)


def _derive_canonical_view(proposal: PlanningProposal) -> CanonicalPlanningView:
    dependencies = tuple(
        _edge_to_domain(edge, proposal.submitted_at)
        for edge in proposal.dependency_edges
    )
    blocking_conditions = tuple(
        _blocker_to_domain(blocker) for blocker in proposal.blocking_conditions
    )
    return CanonicalPlanningView(
        project_key=proposal.project_key,
        proposal_id=proposal.proposal_id,
        proposal_revision=proposal.proposal_revision,
        source_revision=proposal.source_revision,
        # AK3 derivation: a successfully validated proposal is VALIDATED, never
        # the raw SUBMITTED status the agent supplied.
        proposal_status=ProposalStatus.VALIDATED,
        dependencies=dependencies,
        blocking_conditions=blocking_conditions,
        metadata_by_story=_to_metadata(proposal),
    )


def _edge_to_domain(
    edge: ProposalDependencyEdge, submitted_at: datetime
) -> StoryDependency:
    return StoryDependency(
        story_id=edge.story_id,
        depends_on_story_id=edge.depends_on_story_id,
        kind=edge.kind,
        created_at=submitted_at,
    )


def _blocker_to_domain(blocker: ProposalBlockingCondition) -> BlockingCondition:
    return BlockingCondition(
        story_id=blocker.story_id,
        kind=_map_blocking_kind(blocker.kind),
        provenance=BlockingConditionProvenance.DEPENDENCY_GRAPH,
        reason_code=blocker.reason_code,
        source_story_id=blocker.source_story_id,
        source_gate_id=blocker.source_gate_id,
        detail=blocker.detail,
    )


def _persist(
    view: CanonicalPlanningView,
    proposal: PlanningProposal,
    accessor: PlanningProjectionAccessor,
) -> None:
    for metadata in view.metadata_by_story:
        accessor.write_projection(
            PlanningSchemaKind.PLANNED_STORY,
            PlannedStoryRecord(
                project_key=metadata.project_key,
                story_id=metadata.story_id,
                participating_repos=metadata.participating_repos,
                planning_status="UNSTARTED",
                is_hard_truth=metadata.is_hard_truth,
                revision=proposal.proposal_revision,
            ),
        )

    for edge in proposal.dependency_edges:
        accessor.write_projection(
            PlanningSchemaKind.DEPENDENCY_EDGE,
            DependencyEdgeRecord(
                project_key=proposal.project_key,
                story_id=edge.story_id,
                depends_on_story_id=edge.depends_on_story_id,
                kind=edge.kind.value,
                rationale=edge.rationale,
                is_hard_truth=_provenance_is_hard(edge.provenance),
                created_at=proposal.submitted_at.isoformat(),
                revision=proposal.proposal_revision,
            ),
        )

    for index, blocker in enumerate(proposal.blocking_conditions):
        domain = _blocker_to_domain(blocker)
        accessor.write_projection(
            PlanningSchemaKind.BLOCKING_CONDITION,
            BlockingConditionRecord(
                project_key=proposal.project_key,
                blocker_id=f"{proposal.proposal_id}:blk:{index}",
                story_id=blocker.story_id,
                kind=domain.kind.value,
                provenance=domain.provenance.value,
                reason_code=blocker.reason_code,
                source_story_id=blocker.source_story_id,
                source_gate_id=blocker.source_gate_id,
                detail=blocker.detail,
                is_hard_truth=_provenance_is_hard(blocker.provenance),
                revision=proposal.proposal_revision,
            ),
        )

    for gate in proposal.gates:
        accessor.write_projection(
            PlanningSchemaKind.GATE,
            GateRecord(
                project_key=proposal.project_key,
                gate_id=gate.gate_id,
                story_id=gate.story_id,
                gate_kind=gate.gate_kind,
                state="open",
                reason_code=gate.reason_code,
                is_blocking=gate.is_blocking,
                revision=proposal.proposal_revision,
            ),
        )


def ingest_proposal(
    proposal: PlanningProposal,
    *,
    accessor: PlanningProjectionAccessor,
    audit: PlanningAuditEmitter | None = None,
) -> CanonicalPlanningView:
    """Validate, normalize and persist a proposal into the canonical view.

    FAIL-CLOSED: consistency is validated BEFORE any persistence; an
    inconsistent proposal is rejected wholesale (no partial uptake). On success
    the canonical AK3-derived view is persisted through the planning projection
    write path and the relevant audit events are emitted.

    Args:
        proposal: The raw agent ``PlanningProposal``.
        accessor: The planning projection write path.
        audit: Optional audit emitter (``dependency_recorded`` per edge).

    Returns:
        The canonical AK3-derived ``CanonicalPlanningView``.

    Raises:
        ProposalInconsistentError: If the proposal is internally inconsistent.
    """
    _validate_consistency(proposal)
    view = _derive_canonical_view(proposal)
    _persist(view, proposal, accessor)

    if audit is not None:
        for edge in proposal.dependency_edges:
            audit.dependency_recorded(
                story_id=edge.story_id,
                depends_on_id=edge.depends_on_story_id,
                project_key=proposal.project_key,
            )

    return view
