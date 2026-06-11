"""ProposalIngest: validate + normalize + persist a PlanningProposal (FK-70 §70.7b/c).

The ingest path takes a raw, agent-supplied ``PlanningProposal`` and turns it
into the canonical AK3 planning view. The canonical view is an AK3-owned
DERIVATION, never the raw agent answer (FK-70 §70.7b rule 3). Ingest is
fail-closed: an invalid or internally inconsistent proposal is rejected wholesale
(no partial silent uptake). Statements without provenance/evidence are kept as
hints and are never promoted to hard truth (§70.7a #3).
"""

from __future__ import annotations

from agentkit.execution_planning.proposal_ingest.errors import (
    ProposalInconsistentError,
    ProposalIngestError,
)
from agentkit.execution_planning.proposal_ingest.ingest import (
    CanonicalPlanningView,
    ingest_proposal,
)

__all__ = [
    "CanonicalPlanningView",
    "ProposalInconsistentError",
    "ProposalIngestError",
    "ingest_proposal",
]
