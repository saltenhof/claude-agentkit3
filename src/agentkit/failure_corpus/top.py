"""FailureCorpus top component (FK-41 §41.1, AG3-078).

Complete contract surface with six methods. All five non-record_incident methods
are implemented in AG3-078 (PatternPromotion, CheckFactory, Effectiveness, CLI).

Sources:
- FK-41 §41.1 -- six top methods
- FK-41 §41.5 -- PatternPromotion
- FK-41 §41.6 -- CheckFactory (6-step flow)
- FK-41 §41.6.7 -- Effectiveness tracking
- bc-cut-decisions §BC 13 -- top surface, subs
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agentkit.core_types import FailureCategory
from agentkit.failure_corpus.pattern import PatternRiskLevel, PromotionRule
from agentkit.failure_corpus.types import CheckId, IncidentId, PatternId

if TYPE_CHECKING:
    from agentkit.failure_corpus.check_factory import CheckFactory
    from agentkit.failure_corpus.check_proposal import CheckProposalRecord
    from agentkit.failure_corpus.effectiveness import CheckEffectivenessTracker
    from agentkit.failure_corpus.incident import IncidentCandidate
    from agentkit.failure_corpus.incident_triage import IncidentTriage
    from agentkit.failure_corpus.pattern_promotion import PatternPromotion
    from agentkit.state_backend.store.fc_check_proposal_repository import (
        FcCheckProposalRepository,
    )


class PatternDecision(StrEnum):
    """Human decision over a pattern candidate (FK-41 §41.1).

    Attributes:
        ACCEPTED: Pattern confirmed.
        REJECTED: Pattern rejected.
    """

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CheckApprovalDecision(StrEnum):
    """Human decision over a check proposal (FK-41 §41.1, AG3-078 REVISE added).

    Three-valued (FK-41 §41.6.5): APPROVED / REJECTED / REVISE.

    Attributes:
        APPROVED: Check approved; creates implementation story + sets ACTIVE.
        REJECTED: Check rejected; no story created.
        REVISE: Rejected with revision request; current proposal gets
            ``rejected_reason="superseded_by_revision"`` and a new DRAFT
            is created. No new CheckStatus value (lifecycle stays 5-valued).
    """

    APPROVED = "approved"
    REJECTED = "rejected"
    REVISE = "revise"


class PatternCandidate(BaseModel):
    """Proposal from the clustering (FK-41 §41.5, AG3-078).

    Richer model now that PatternPromotion is functional.

    Attributes:
        pattern_id: Proposed pattern identity (FP-NNNN).
        category: Failure category of the cluster.
        symptom_signature: Deterministic 16-hex-char cluster key (AG3-078 §2.1.1).
        promotion_rule: The qualifying promotion rule.
        incident_refs: Incident IDs in the cluster.
        invariant_candidate: Candidate invariant text (pre-LLM-sharpening).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_id: PatternId
    category: FailureCategory
    symptom_signature: str
    promotion_rule: PromotionRule
    incident_refs: list[str]
    invariant_candidate: str


class FailurePattern(BaseModel):
    """Confirmed pattern (lifecycle stage ``accepted``, AG3-078)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_id: PatternId


class CheckProposal(BaseModel):
    """Generated check proposal (FK-41 §41.6.4, AG3-078).

    Attributes:
        check_id: Unique check identity (CHK-NNNN).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: CheckId


class EffectivenessReport(BaseModel):
    """Aggregate effectiveness report over a window (FK-41 §41.6.7, AG3-078).

    Attributes:
        window_days: Observation window in days.
        updated_count: Number of ACTIVE checks whose counters were updated.
        deactivated_count: Number of checks auto-deactivated (RETIRED).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_days: int
    updated_count: int = 0
    deactivated_count: int = 0


class FailureCorpus:
    """Top component of the failure-corpus BC (FK-41 §41.1, AG3-078).

    Args:
        incident_triage: The functional IncidentTriage sub (AG3-028).
        pattern_promotion: PatternPromotion sub (AG3-078).
        check_factory: CheckFactory sub (AG3-078).
        effectiveness_tracker: CheckEffectivenessTracker sub (AG3-078).
        check_repo: Read adapter for ``fc_check_proposals`` (bound for the thin
            ``list_checks`` read delegation, FK-41 §41.9; AG3-078).
        project_key: Project key the corpus is bound to (read scope for
            ``list_checks``).
    """

    def __init__(
        self,
        incident_triage: IncidentTriage,
        pattern_promotion: PatternPromotion | None = None,
        check_factory: CheckFactory | None = None,
        effectiveness_tracker: CheckEffectivenessTracker | None = None,
        check_repo: FcCheckProposalRepository | None = None,
        project_key: str | None = None,
    ) -> None:
        self._incident_triage = incident_triage
        self._pattern_promotion = pattern_promotion
        self._check_factory = check_factory
        self._effectiveness_tracker = effectiveness_tracker
        self._check_repo = check_repo
        self._project_key = project_key

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
        """Cluster OBSERVED incidents into PatternCandidates (FK-41 §41.5, AG3-078).

        Delegates to ``PatternPromotion.suggest_patterns``.

        Returns:
            List of ``PatternCandidate`` objects for qualifying clusters.

        Raises:
            RuntimeError: If PatternPromotion is not wired (FAIL-CLOSED).
        """
        if self._pattern_promotion is None:
            raise RuntimeError(
                "suggest_patterns requires PatternPromotion to be wired "
                "(FAIL-CLOSED: pattern_promotion is None)"
            )
        return self._pattern_promotion.suggest_patterns()

    def confirm_pattern(
        self,
        pattern_id: PatternId,
        decision: PatternDecision,
        *,
        invariant: str | None = None,
        risk_level: PatternRiskLevel | None = None,
        promotion_rule: PromotionRule | None = None,
        incident_refs: list[str] | None = None,
        category: FailureCategory | None = None,
    ) -> FailurePattern:
        """Human confirmation of a pattern candidate (FK-41 §41.5.3, AG3-078).

        Args:
            pattern_id: Pattern identity (FP-NNNN).
            decision: Human decision (ACCEPTED or REJECTED).
            invariant: Invariant text (required for ACCEPTED).
            risk_level: Risk level (required for ACCEPTED).
            promotion_rule: Promotion rule (required for ACCEPTED).
            incident_refs: Incident references.
            category: Failure category (required for ACCEPTED).

        Returns:
            ``FailurePattern`` wrapping the persisted pattern_id.

        Raises:
            RuntimeError: If PatternPromotion is not wired (FAIL-CLOSED).
        """
        if self._pattern_promotion is None:
            raise RuntimeError(
                "confirm_pattern requires PatternPromotion to be wired "
                "(FAIL-CLOSED: pattern_promotion is None)"
            )
        self._pattern_promotion.confirm_pattern(
            pattern_id,
            decision,
            invariant=invariant,
            risk_level=risk_level,
            promotion_rule=promotion_rule,
            incident_refs=incident_refs,
            category=category,
        )
        return FailurePattern(pattern_id=pattern_id)

    def derive_check(self, pattern_id: PatternId) -> CheckProposal:
        """Derive a check proposal from an ACCEPTED pattern (FK-41 §41.6, AG3-078).

        6-step CheckFactory flow: step1 LLM invariant sharpening, step2
        deterministic check-type mapping, step3 fc_check_proposals DRAFT.

        Args:
            pattern_id: Pattern identity (FP-NNNN); must be ACCEPTED.

        Returns:
            ``CheckProposal`` wrapping the created CHK-NNNN.

        Raises:
            RuntimeError: If CheckFactory is not wired (FAIL-CLOSED).
            FailureCorpusError: If pattern is not ACCEPTED or not found.
        """
        if self._check_factory is None:
            raise RuntimeError(
                "derive_check requires CheckFactory to be wired "
                "(FAIL-CLOSED: check_factory is None)"
            )
        record = self._check_factory.derive_check(pattern_id)
        return CheckProposal(check_id=CheckId(record.check_id))

    def approve_check(
        self,
        check_id: CheckId,
        decision: CheckApprovalDecision,
        *,
        rejected_reason: str | None = None,
    ) -> CheckProposal:
        """Human approval of a check proposal (FK-41 §41.6.5, AG3-078).

        Three-valued decision: APPROVED (creates story + sets ACTIVE),
        REJECTED (sets REJECTED), REVISE (old -> REJECTED superseded_by_revision,
        new DRAFT created).

        Args:
            check_id: Check identity (CHK-NNNN).
            decision: Human decision (APPROVED / REJECTED / REVISE).
            rejected_reason: Optional rejection reason text.

        Returns:
            ``CheckProposal`` wrapping the resulting check_id (new for REVISE).

        Raises:
            RuntimeError: If CheckFactory is not wired (FAIL-CLOSED).
        """
        if self._check_factory is None:
            raise RuntimeError(
                "approve_check requires CheckFactory to be wired "
                "(FAIL-CLOSED: check_factory is None)"
            )
        result_check_id = self._check_factory.approve_check(
            check_id, decision, rejected_reason=rejected_reason
        )
        return CheckProposal(check_id=result_check_id)

    def report_effectiveness(self, window_days: int = 90) -> EffectivenessReport:
        """Report and update effectiveness of all ACTIVE checks (FK-41 §41.6.7, AG3-078).

        Reads qa_check_outcomes by check_proposal_ref, aggregates true/false positives
        and no-findings, writes back to fc_check_proposals, auto-deactivates where
        tp==0 AND fp>3 (except CRITICAL risk patterns).

        Args:
            window_days: Observation window in days (default 90).

        Returns:
            ``EffectivenessReport`` with updated/deactivated counts.

        Raises:
            RuntimeError: If effectiveness tracker is not wired (FAIL-CLOSED).
        """
        if self._effectiveness_tracker is None:
            raise RuntimeError(
                "report_effectiveness requires CheckEffectivenessTracker to be wired "
                "(FAIL-CLOSED: effectiveness_tracker is None)"
            )
        return self._effectiveness_tracker.report_effectiveness(window_days=window_days)

    def list_checks(
        self, *, pattern_id: str | None = None
    ) -> list[CheckProposalRecord]:
        """List check proposals for the bound project (FK-41 §41.9, AG3-078).

        Thin read delegation over the bound ``FcCheckProposalRepository``. When
        ``pattern_id`` is given the result is the proposals of that pattern
        restricted to the bound ``project_key``; otherwise it is all proposals
        of the bound ``project_key``. No business logic — read-only.

        Args:
            pattern_id: Optional pattern identity (FP-NNNN) to filter by.

        Returns:
            The matching ``CheckProposalRecord`` objects (deterministic order
            from the repository, by ``check_id``).

        Raises:
            RuntimeError: If the check repository or project key is not wired
                (FAIL-CLOSED).
        """
        if self._check_repo is None or self._project_key is None:
            raise RuntimeError(
                "list_checks requires check_repo and project_key to be wired "
                "(FAIL-CLOSED: check_repo or project_key is None)"
            )
        if pattern_id is not None:
            return [
                record
                for record in self._check_repo.list_for_pattern(pattern_id)
                if record.project_key == self._project_key
            ]
        return self._check_repo.list_for_project(self._project_key)


__all__ = [
    "CheckApprovalDecision",
    "CheckProposal",
    "EffectivenessReport",
    "FailureCorpus",
    "FailurePattern",
    "PatternCandidate",
    "PatternDecision",
]
