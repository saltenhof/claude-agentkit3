"""Failure-corpus BC: top-surface + IncidentTriage (FK-41, AG3-028).

Re-export of the public contract surface. Only ``record_incident`` is
functional in this story; the remaining top methods are contract slots for
follow-up stories (PatternPromotion/CheckFactory).

``IncidentStatus`` is the canonical SSOT in ``agentkit.core_types`` (CONFLICT-1)
and is only passed through here.
"""

from __future__ import annotations

from agentkit.core_types import FailureCategory, IncidentStatus
from agentkit.failure_corpus.check_proposal import (
    CheckProposalRecord,
    FalsePositiveRisk,
)
from agentkit.failure_corpus.errors import (
    FailureCorpusError,
    IncidentRejectedError,
    IncidentRejectReason,
)
from agentkit.failure_corpus.incident import (
    Incident,
    IncidentCandidate,
    IncidentDraft,
)
from agentkit.failure_corpus.incident_triage import (
    IncidentNormalizer,
    IncidentTriage,
    IngressCriteria,
)
from agentkit.failure_corpus.pattern import (
    FailurePatternRecord,
    PatternRiskLevel,
    PromotionRule,
)
from agentkit.failure_corpus.ports import IncidentWriterPort, ProjectionReaderPort
from agentkit.failure_corpus.top import (
    CheckApprovalDecision,
    CheckProposal,
    EffectivenessReport,
    FailureCorpus,
    FailurePattern,
    PatternCandidate,
    PatternDecision,
)
from agentkit.failure_corpus.types import (
    CheckId,
    IncidentId,
    IncidentRole,
    IncidentSeverity,
    PatternId,
)

__all__ = [
    "CheckApprovalDecision",
    "CheckId",
    "CheckProposal",
    "CheckProposalRecord",
    "EffectivenessReport",
    "FailureCategory",
    "FailureCorpus",
    "FailureCorpusError",
    "FailurePattern",
    "FailurePatternRecord",
    "FalsePositiveRisk",
    "Incident",
    "IncidentCandidate",
    "IncidentDraft",
    "IncidentId",
    "IncidentNormalizer",
    "IncidentRejectReason",
    "IncidentRejectedError",
    "IncidentRole",
    "IncidentSeverity",
    "IncidentStatus",
    "IncidentTriage",
    "IncidentWriterPort",
    "IngressCriteria",
    "PatternCandidate",
    "PatternDecision",
    "PatternId",
    "PatternRiskLevel",
    "ProjectionReaderPort",
    "PromotionRule",
]
