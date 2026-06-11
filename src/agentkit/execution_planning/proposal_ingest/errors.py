"""Errors for proposal ingest (FK-70 §70.7b, FAIL-CLOSED)."""

from __future__ import annotations

from agentkit.exceptions import AgentKitError

__all__ = ["ProposalInconsistentError", "ProposalIngestError"]


class ProposalIngestError(AgentKitError):
    """Base error for a rejected proposal ingest (no partial uptake)."""


class ProposalInconsistentError(ProposalIngestError):
    """Raised when a proposal is internally inconsistent (FK-70 §70.7b).

    FAIL-CLOSED: an inconsistent proposal (e.g. an edge/gate/blocker referencing
    a story outside the considered set, a self-edge, a duplicate edge, an unknown
    blocker kind) is rejected wholesale rather than partially applied.
    """
