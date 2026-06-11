"""PlanningProposal: versioned Agent->AK3 handover contract (FK-70 §70.7b/§70.7c).

Agents may analyse dependencies, gates, conflict surfaces and execution waves,
but the official handover to AK3 is NOT free prose -- it is a structured,
versioned ``PlanningProposal``. AK3 validates, normalizes and persists the
proposal; the canonical ``ExecutionPlan`` stays an AK3-owned derivation and is
never the unchecked agent answer (FK-70 §70.7b rule 1-3).

The proposal carries its own typed sub-structures (proposed dependency edges,
blocking conditions, gates, conflict/scope surfaces, optional waves/batches,
evidence/provenance) plus ``proposal_revision``/``source_revision``. The
domain truth types (``BlockingCondition``/``Gate``/``ExecutionWave``) are NOT
redefined here -- they are AG3-098-owned and only the agent's *proposed* shape
is modeled at the handover boundary; ingest maps these onto the canonical
AG3-098 domain types.

Sources:
- FK-70 §70.7b -- handover contract minimum contents + AK3-derivation rule
- FK-70 §70.7c -- structured proposal contract is the standard interface (no DSL)
- FK-70 §70.7a #3 -- provenance rule (hint vs hard truth)
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentkit.core_types import StoryDependencyKind
from agentkit.execution_planning.planning_model.metadata import Provenance

__all__ = [
    "PlanningProposal",
    "ProposalBatch",
    "ProposalBlockingCondition",
    "ProposalConflictSurface",
    "ProposalDependencyEdge",
    "ProposalGate",
    "ProposalScopeSurface",
    "ProposalSourceKind",
    "ProposalStatus",
    "ProposalWave",
]


class ProposalSourceKind(StrEnum):
    """How the proposal was authored (FK-70 §70.7c).

    The structured canonical form is the standard interface; a project rulebook
    DSL is an optional *input format* that compiles into the canonical proposal.
    """

    CANONICAL_STRUCTURED = "canonical_structured"
    RULEBOOK_DSL = "rulebook_dsl"


class ProposalStatus(StrEnum):
    """Lifecycle status of a proposal (formal.execution-planning.entities)."""

    SUBMITTED = "submitted"
    VALIDATED = "validated"
    REJECTED = "rejected"
    APPLIED = "applied"


class ProposalDependencyEdge(BaseModel):
    """One proposed dependency edge inside a proposal (FK-70 §70.7b).

    Mirrors the agent's proposed edge shape at the handover boundary. Ingest
    maps it onto the canonical ``StoryDependency`` domain type (AG3-098/-021);
    this proposal type does NOT replace the domain edge.

    Attributes:
        story_id: Dependent story.
        depends_on_story_id: Story it depends on.
        kind: Proposed dependency kind (FK-70 §70.4.2 vocabulary).
        rationale: Optional rationale for the edge.
        provenance: Optional provenance/evidence (hint if absent/evidence-less).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    depends_on_story_id: str
    kind: StoryDependencyKind
    rationale: str | None = None
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def _validate_no_self_edge(self) -> ProposalDependencyEdge:
        if self.story_id == self.depends_on_story_id:
            raise ValueError("proposed dependency edge must not point to itself")
        return self


class ProposalBlockingCondition(BaseModel):
    """One proposed blocking condition (FK-70 §70.7b).

    Attributes:
        story_id: Blocked story.
        kind: Blocker class (wire string; mapped to the AG3-098
            ``BlockingConditionKind`` on ingest).
        reason_code: Closed reason code.
        source_story_id: Optional source story for a dependency blocker.
        source_gate_id: Optional source gate id.
        detail: Optional detail.
        provenance: Optional provenance/evidence.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    kind: str
    reason_code: str
    source_story_id: str | None = None
    source_gate_id: str | None = None
    detail: str | None = None
    provenance: Provenance | None = None


class ProposalGate(BaseModel):
    """One proposed gate (human or external) (FK-70 §70.7b/§70.5.3).

    Attributes:
        story_id: Story the gate guards.
        gate_id: Stable gate id.
        gate_kind: ``human`` or ``external``.
        reason_code: Closed reason code.
        is_blocking: Whether an open gate blocks readiness.
        provenance: Optional provenance/evidence.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    gate_id: str
    gate_kind: str
    reason_code: str
    is_blocking: bool = True
    provenance: Provenance | None = None


class ProposalConflictSurface(BaseModel):
    """A proposed conflict surface between stories/repos (FK-70 §70.7b)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    surface_id: str
    story_ids: tuple[str, ...] = Field(default_factory=tuple)
    detail: str | None = None
    provenance: Provenance | None = None


class ProposalScopeSurface(BaseModel):
    """A proposed scope surface for a story (FK-70 §70.7b)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    surface_id: str
    story_id: str
    detail: str | None = None
    provenance: Provenance | None = None


class ProposalWave(BaseModel):
    """An optionally proposed execution wave (FK-70 §70.7b)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    wave_id: str
    wave_order: int = Field(ge=0)
    story_ids: tuple[str, ...] = Field(default_factory=tuple)


class ProposalBatch(BaseModel):
    """An optionally proposed batch grouping (FK-70 §70.7b)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: str
    story_ids: tuple[str, ...] = Field(default_factory=tuple)


class PlanningProposal(BaseModel):
    """Structured, versioned Agent->AK3 handover contract (FK-70 §70.7b/§70.7c).

    The official handover surface from an agent to AK3. AK3 validates,
    normalizes and persists it; the canonical ``ExecutionPlan`` remains an
    AK3-owned derivation and is never this raw proposal.

    Attributes:
        proposal_id: Stable proposal identity.
        project_key: Tenant/project scope key.
        producer_principal: Authoring agent/principal id.
        source_kind: How the proposal was authored.
        considered_story_ids: The story set the proposal reasons about (§70.7b).
        dependency_edges: Proposed dependency edges.
        blocking_conditions: Proposed blocking conditions.
        gates: Proposed gates.
        conflict_surfaces: Proposed conflict surfaces.
        scope_surfaces: Proposed scope surfaces.
        waves: Optional proposed waves.
        batches: Optional proposed batches.
        proposal_revision: Monotonic revision of the proposal itself (§70.7b).
        source_revision: Revision of the upstream source the proposal is built
            on (e.g. graph/rulebook revision) (§70.7b).
        status: Proposal lifecycle status.
        submitted_at: Submission timestamp.
        provenance: Optional proposal-level provenance/evidence.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str
    project_key: str
    producer_principal: str
    source_kind: ProposalSourceKind = ProposalSourceKind.CANONICAL_STRUCTURED
    considered_story_ids: tuple[str, ...] = Field(default_factory=tuple)
    dependency_edges: tuple[ProposalDependencyEdge, ...] = Field(default_factory=tuple)
    blocking_conditions: tuple[ProposalBlockingCondition, ...] = Field(
        default_factory=tuple
    )
    gates: tuple[ProposalGate, ...] = Field(default_factory=tuple)
    conflict_surfaces: tuple[ProposalConflictSurface, ...] = Field(default_factory=tuple)
    scope_surfaces: tuple[ProposalScopeSurface, ...] = Field(default_factory=tuple)
    waves: tuple[ProposalWave, ...] = Field(default_factory=tuple)
    batches: tuple[ProposalBatch, ...] = Field(default_factory=tuple)
    proposal_revision: int = Field(ge=1)
    source_revision: int = Field(ge=0)
    status: ProposalStatus = ProposalStatus.SUBMITTED
    submitted_at: datetime
    provenance: Provenance | None = None
