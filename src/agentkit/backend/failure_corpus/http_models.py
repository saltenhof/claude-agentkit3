"""HTTPS wire models for writer-owned failure-corpus mutations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agentkit.backend.core_types import FailureCategory
from agentkit.backend.failure_corpus.pattern import PatternRiskLevel, PromotionRule
from agentkit.backend.failure_corpus.top import CheckApprovalDecision, PatternDecision
from agentkit.backend.failure_corpus.types import IncidentRole, IncidentSeverity


class FailureCorpusIncidentMutationRequest(BaseModel):
    """Authenticated request to record one project-scoped incident."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str = Field(min_length=1)
    story_id: str
    run_id: str
    category: FailureCategory
    severity: IncidentSeverity
    phase: str
    role: IncidentRole
    model: str
    symptom: str
    evidence: tuple[str, ...] = ()
    merge_blocked: bool = False


class FailureCorpusIncidentMutationResponse(BaseModel):
    """Identity allocated by the active writer for a recorded incident."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str


class FailureCorpusPatternReviewRequest(BaseModel):
    """Authenticated human decision over one pattern candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str = Field(min_length=1)
    decision: PatternDecision
    invariant: str | None = None
    risk_level: PatternRiskLevel | None = None
    promotion_rule: PromotionRule | None = None
    category: FailureCategory | None = None


class FailureCorpusPatternReviewResponse(BaseModel):
    """Pattern identity and decision committed by the active writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pattern_id: str
    decision: PatternDecision


class FailureCorpusCheckReviewRequest(BaseModel):
    """Authenticated human decision over one check proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str = Field(min_length=1)
    decision: CheckApprovalDecision
    rejected_reason: str | None = None


class FailureCorpusCheckReviewResponse(BaseModel):
    """Check identity and decision committed by the active writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str
    decision: CheckApprovalDecision


class FailureCorpusEffectivenessRequest(BaseModel):
    """Authenticated request to update check-effectiveness state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op_id: str = Field(min_length=1)
    window_days: int = 90


class FailureCorpusEffectivenessResponse(BaseModel):
    """Aggregate effectiveness result committed by the active writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_days: int
    updated_count: int
    deactivated_count: int


__all__ = [
    "FailureCorpusCheckReviewRequest",
    "FailureCorpusCheckReviewResponse",
    "FailureCorpusEffectivenessRequest",
    "FailureCorpusEffectivenessResponse",
    "FailureCorpusIncidentMutationRequest",
    "FailureCorpusIncidentMutationResponse",
    "FailureCorpusPatternReviewRequest",
    "FailureCorpusPatternReviewResponse",
]
