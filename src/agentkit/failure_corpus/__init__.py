"""Failure-Corpus-BC: Top-Surface + IncidentTriage (FK-41, AG3-028).

Re-Export der oeffentlichen Vertrags-Surface. Nur ``record_incident`` ist in
dieser Story funktional; die uebrigen Top-Methoden sind Vertrags-Slots fuer
Folge-Stories (PatternPromotion/CheckFactory).

``IncidentStatus`` ist die kanonische SSOT in ``agentkit.core_types`` (KONFLIKT-1)
und wird hier nur durchgereicht.
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
