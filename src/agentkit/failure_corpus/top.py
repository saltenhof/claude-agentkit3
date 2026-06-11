"""FailureCorpus top component (FK-41 §41.1).

Complete contract surface with six methods. Only ``record_incident`` is
functional in this story (AG3-028) — it is the receiver contract that other BCs
(governance-and-guards / verify-system / story-closure) need. The five remaining
methods raise ``NotImplementedError`` with a rationale + reference to their
follow-up story (ZERO DEBT: contract slot, not half-finished).

Follow-up stories:
- ``suggest_patterns``/``confirm_pattern``: PatternPromotion sub
  (failure-corpus.A4, after THEME-009 / LlmEvaluator).
- ``derive_check``/``approve_check``: CheckFactory sub (failure-corpus.A5).
- ``report_effectiveness``: effectiveness tracking (failure-corpus.A7).

Sources:
- FK-41 §41.1 -- six top methods
- bc-cut-decisions §BC 13 -- top surface, subs
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agentkit.failure_corpus.types import CheckId, IncidentId, PatternId

if TYPE_CHECKING:
    from agentkit.failure_corpus.incident import IncidentCandidate
    from agentkit.failure_corpus.incident_triage import IncidentTriage


class PatternDecision(StrEnum):
    """Human decision over a pattern candidate (FK-41 §41.1).

    Attributes:
        ACCEPTED: Pattern confirmed.
        REJECTED: Pattern rejected.
    """

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CheckApprovalDecision(StrEnum):
    """Human decision over a check proposal (FK-41 §41.1).

    Attributes:
        APPROVED: Check approved.
        REJECTED: Check rejected.
    """

    APPROVED = "approved"
    REJECTED = "rejected"


class PatternCandidate(BaseModel):
    """Proposal from the clustering (FK-41 pattern lifecycle, follow-up story)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_id: PatternId


class FailurePattern(BaseModel):
    """Confirmed pattern (lifecycle stage ``accepted``, follow-up story)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_id: PatternId


class CheckProposal(BaseModel):
    """Generated check proposal (FK-41 CheckFactory, follow-up story)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: CheckId


class EffectivenessReport(BaseModel):
    """Aggregate report over an effectiveness window (follow-up story)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_days: int


class FailureCorpus:
    """Top component of the failure-corpus BC (FK-41 §41.1).

    Args:
        incident_triage: The functional IncidentTriage sub (AG3-028).
        pattern_promotion: Stub slot for the PatternPromotion sub (follow-up story).
        check_factory: Stub slot for the CheckFactory sub (follow-up story).
    """

    def __init__(
        self,
        incident_triage: IncidentTriage,
        pattern_promotion: object | None = None,
        check_factory: object | None = None,
    ) -> None:
        self._incident_triage = incident_triage
        self._pattern_promotion = pattern_promotion
        self._check_factory = check_factory

    def record_incident(self, candidate: IncidentCandidate) -> IncidentId:
        """Admits an incident candidate and persists it (FK-41 §41.1).

        Delegates to the ``IncidentTriage`` (IngressCriteria -> Normalizer ->
        ``write_projection(FC_INCIDENTS, incident)``). Receiver contract for
        governance-and-guards / verify-system / story-closure.

        Args:
            candidate: Incoming incident candidate.

        Returns:
            The assigned ``IncidentId``.

        Raises:
            IncidentRejectedError: If the IngressCriteria reject the candidate
                (FAIL-CLOSED).
        """
        return self._incident_triage.ingest(candidate)

    def suggest_patterns(self) -> list[PatternCandidate]:
        """NOT IMPLEMENTED — PatternPromotion sub (follow-up story failure-corpus.A4).

        Raises:
            NotImplementedError: PatternPromotion needs LlmEvaluator (THEME-009)
                and is not part of AG3-028.
        """
        raise NotImplementedError(
            "suggest_patterns belongs to the PatternPromotion sub (failure-corpus.A4, "
            "follow-up story after THEME-009/LlmEvaluator) and is out of scope in AG3-028."
        )

    def confirm_pattern(
        self,
        pattern_id: PatternId,
        decision: PatternDecision,
    ) -> FailurePattern:
        """NOT IMPLEMENTED — PatternPromotion sub (follow-up story failure-corpus.A4).

        Args:
            pattern_id: Pattern identity.
            decision: Human decision.

        Raises:
            NotImplementedError: PatternPromotion is not part of AG3-028.
        """
        raise NotImplementedError(
            "confirm_pattern belongs to the PatternPromotion sub (failure-corpus.A4, "
            "follow-up story) and is out of scope in AG3-028."
        )

    def derive_check(self, pattern_id: PatternId) -> CheckProposal:
        """NOT IMPLEMENTED — CheckFactory sub (follow-up story failure-corpus.A5).

        Args:
            pattern_id: Pattern identity from which a check would be derived.

        Raises:
            NotImplementedError: CheckFactory is not part of AG3-028.
        """
        raise NotImplementedError(
            "derive_check belongs to the CheckFactory sub (failure-corpus.A5, "
            "follow-up story) and is out of scope in AG3-028."
        )

    def approve_check(
        self,
        check_id: CheckId,
        decision: CheckApprovalDecision,
    ) -> CheckProposal:
        """NOT IMPLEMENTED — CheckFactory sub (follow-up story failure-corpus.A5).

        Args:
            check_id: Check identity.
            decision: Human approval decision.

        Raises:
            NotImplementedError: CheckFactory is not part of AG3-028.
        """
        raise NotImplementedError(
            "approve_check belongs to the CheckFactory sub (failure-corpus.A5, "
            "follow-up story) and is out of scope in AG3-028."
        )

    def report_effectiveness(self, window_days: int = 90) -> EffectivenessReport:
        """NOT IMPLEMENTED — effectiveness tracking (follow-up story failure-corpus.A7).

        Args:
            window_days: Observation window in days.

        Raises:
            NotImplementedError: Effectiveness tracking is not part of AG3-028.
        """
        raise NotImplementedError(
            "report_effectiveness belongs to Effectiveness tracking "
            "(failure-corpus.A7, follow-up story) and is out of scope in AG3-028."
        )


__all__ = [
    "CheckApprovalDecision",
    "CheckProposal",
    "EffectivenessReport",
    "FailureCorpus",
    "FailurePattern",
    "PatternCandidate",
    "PatternDecision",
]
