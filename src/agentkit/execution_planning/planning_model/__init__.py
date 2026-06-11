"""PlanningModel: typed Agent->AK3 handover, metadata and rulebook contracts (BC14).

This subpackage owns the typed FK-70 §70.7a/§70.7b/§70.7d contract models that
feed the canonical planning view: the versioned ``PlanningProposal`` handover
contract, the per-story ``PlanningMetadata`` contract, and the project-specific
``RulebookRevision`` / ``RulebookCompileResult`` rulebook model. These are pure
data contracts (Pydantic v2, frozen); the ingest/compile behaviour lives in
``proposal_ingest`` / ``rulebook`` and persistence in ``persistence``.

Sources:
- FK-70 §70.7a -- planning-metadata contract (structure, dependencies, gates,
  hints, provenance)
- FK-70 §70.7b/§70.7c -- ``PlanningProposal`` handover contract
- FK-70 §70.7d -- project rulebook (distinct from the FK-20 FlowDefinition DSL)
"""

from __future__ import annotations

from agentkit.execution_planning.planning_model.metadata import (
    GateMetadata,
    PlanningHint,
    PlanningMetadata,
    Provenance,
    ProvenanceReliability,
)
from agentkit.execution_planning.planning_model.proposal import (
    PlanningProposal,
    ProposalBatch,
    ProposalBlockingCondition,
    ProposalConflictSurface,
    ProposalDependencyEdge,
    ProposalGate,
    ProposalScopeSurface,
    ProposalSourceKind,
    ProposalStatus,
    ProposalWave,
)
from agentkit.execution_planning.planning_model.rulebook import (
    CompiledRulebook,
    RulebookCompileResult,
    RulebookCompileStatus,
    RulebookRevision,
    RulebookSchedulingRule,
)

__all__ = [
    "CompiledRulebook",
    "GateMetadata",
    "PlanningHint",
    "PlanningMetadata",
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
    "Provenance",
    "ProvenanceReliability",
    "RulebookCompileResult",
    "RulebookCompileStatus",
    "RulebookRevision",
    "RulebookSchedulingRule",
]
