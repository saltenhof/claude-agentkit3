"""Failure-corpus BC: top-surface + IncidentTriage (FK-41, AG3-028/AG3-078).

Re-export of the public contract surface. AG3-028 delivered ``record_incident``;
AG3-078 added ``suggest_patterns``, ``confirm_pattern``, ``derive_check``,
``approve_check``, ``report_effectiveness`` (PatternPromotion, CheckFactory,
CheckEffectivenessTracker, SonarAcceptFrequencySignal).

``IncidentStatus`` is the canonical SSOT in ``agentkit.core_types`` (CONFLICT-1)
and is only passed through here.
"""

from __future__ import annotations

from agentkit.core_types import FailureCategory, IncidentStatus
from agentkit.failure_corpus.check_factory import (
    F41_070_REFERENCE_EXAMPLE,
    CheckFactory,
    InvariantSharpenerPort,
    StoryCreationPort,
)
from agentkit.failure_corpus.check_proposal import (
    CheckProposalRecord,
    FalsePositiveRisk,
)
from agentkit.failure_corpus.effectiveness import CheckEffectivenessTracker
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
from agentkit.failure_corpus.pattern_promotion import (
    CATEGORY_TO_CHECK_TYPE,
    CHECK_TYPE_FALSE_POSITIVE_RISK,
    PatternPromotion,
    compute_symptom_signature,
)
from agentkit.failure_corpus.ports import IncidentWriterPort, ProjectionReaderPort
from agentkit.failure_corpus.sonar_signal import (
    SonarAcceptFrequencySignal,
    check_accept_frequency,
)
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
    "CATEGORY_TO_CHECK_TYPE",
    "CHECK_TYPE_FALSE_POSITIVE_RISK",
    "CheckApprovalDecision",
    "CheckFactory",
    "CheckId",
    "CheckProposal",
    "CheckProposalRecord",
    "CheckEffectivenessTracker",
    "EffectivenessReport",
    "F41_070_REFERENCE_EXAMPLE",
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
    "InvariantSharpenerPort",
    "PatternCandidate",
    "PatternDecision",
    "PatternId",
    "PatternPromotion",
    "PatternRiskLevel",
    "ProjectionReaderPort",
    "PromotionRule",
    "SonarAcceptFrequencySignal",
    "StoryCreationPort",
    "check_accept_frequency",
    "compute_symptom_signature",
]
