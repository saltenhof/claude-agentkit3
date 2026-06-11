"""Planning-metadata contract (FK-70 §70.7a).

The canonical per-story planning-metadata contract. It is NOT the story
description: it carries structural metadata (equal-ranked ``participating_repos``,
scope/conflict surfaces), dependencies, gate metadata, planning hints and
provenance. All inbound sources (proposal ingest, story creation, admin,
external) must land in this one canonical typed contract before AK3 derives
``READY``, blockers or waves from it.

Normative provenance rule (FK-70 §70.7a #3): a statement WITHOUT provenance or
evidence may be stored as a HINT but must never silently become hard truth.
``PlanningMetadata.is_hard_truth`` encodes this: a metadata record is hard only
when it carries provenance with at least one evidence reference.

Sources:
- FK-70 §70.7a -- planning-metadata contract + provenance rule (#1-#3)
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "GateMetadata",
    "PlanningHint",
    "PlanningMetadata",
    "Provenance",
    "ProvenanceReliability",
]


class ProvenanceReliability(StrEnum):
    """Reliability grade of a provenance statement (FK-70 §70.7a)."""

    AUTHORITATIVE = "authoritative"
    CORROBORATED = "corroborated"
    REPORTED = "reported"
    UNVERIFIED = "unverified"


class Provenance(BaseModel):
    """Where a planning statement came from, on which evidence, how reliable.

    FK-70 §70.7a: provenance records the producer, the evidence basis and the
    reliability grade of a planning statement. A provenance that carries at
    least one ``evidence_refs`` entry promotes the carrying statement to hard
    truth; an empty evidence set keeps it a hint (see
    ``PlanningMetadata.is_hard_truth``).

    Attributes:
        producer_principal: Who supplied the statement (agent/admin/system id).
        evidence_refs: Evidence references backing the statement. Empty => hint.
        reliability: Reliability grade of the statement.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    producer_principal: str
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    reliability: ProvenanceReliability = ProvenanceReliability.UNVERIFIED

    @property
    def has_evidence(self) -> bool:
        """Return whether this provenance carries at least one evidence ref."""

        return len(self.evidence_refs) > 0


class GateMetadata(BaseModel):
    """Gate-metadata entry: an external/human prerequisite for a story.

    FK-70 §70.7a gate metadata: external prerequisites, human gates, required
    approvals, UAT/environment conditions. Modeled typed (not free prose).

    Attributes:
        gate_id: Stable gate identifier.
        gate_kind: Gate class (e.g. ``human``, ``external``).
        reason_code: Closed reason code for the gate.
        is_blocking: Whether an open gate blocks readiness.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_id: str
    gate_kind: str
    reason_code: str
    is_blocking: bool = True


class PlanningHint(BaseModel):
    """Typed planning hint (FK-70 §70.7a planning hints).

    Parallelization, serialization, mutex/conflict indicators. A hint is a
    suggestion, never a hard constraint on its own.

    Attributes:
        hint_kind: Closed hint class (e.g. ``parallelizable``, ``serialize``,
            ``mutex``).
        detail: Optional free-text detail.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    hint_kind: str
    detail: str | None = None


class PlanningMetadata(BaseModel):
    """Canonical per-story planning-metadata contract (FK-70 §70.7a).

    All inbound planning statements normalize into this one typed contract
    before AK3 derives planning state. The provenance rule (§70.7a #3) is
    enforced via ``is_hard_truth``: without provenance evidence the metadata is
    a hint and must not be treated as hard truth by downstream derivation.

    Attributes:
        project_key: Tenant/project scope key.
        story_id: Story this metadata describes.
        participating_repos: Equal-ranked repos (no special role for any one
            repo, §70.7a structural metadata).
        scope_surfaces: Relevant scope surfaces.
        conflict_surfaces: Technical conflict surfaces.
        hard_dependency_ids: Hard story dependencies.
        soft_dependency_ids: Soft/weak story relationships.
        gates: Gate-metadata entries.
        hints: Planning hints.
        provenance: Optional provenance. ``None`` or evidence-less => hint only.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    story_id: str
    participating_repos: tuple[str, ...] = Field(default_factory=tuple)
    scope_surfaces: tuple[str, ...] = Field(default_factory=tuple)
    conflict_surfaces: tuple[str, ...] = Field(default_factory=tuple)
    hard_dependency_ids: tuple[str, ...] = Field(default_factory=tuple)
    soft_dependency_ids: tuple[str, ...] = Field(default_factory=tuple)
    gates: tuple[GateMetadata, ...] = Field(default_factory=tuple)
    hints: tuple[PlanningHint, ...] = Field(default_factory=tuple)
    provenance: Provenance | None = None

    @property
    def is_hard_truth(self) -> bool:
        """Return whether this metadata may be treated as hard truth.

        FK-70 §70.7a #3: a statement without provenance/evidence stays a hint.
        Hard truth requires provenance carrying at least one evidence reference.
        """

        return self.provenance is not None and self.provenance.has_evidence
