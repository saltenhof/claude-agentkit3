"""CheckEffectivenessTracker for the failure-corpus BC (FK-41 §41.6.7, AG3-078).

Periodic job: reads ``qa_check_outcomes`` by ``check_proposal_ref``, aggregates
true/false positives and no-findings per ACTIVE check, writes back to
``fc_check_proposals``, and auto-deactivates checks where tp==0 AND fp>3
(except CRITICAL risk patterns).

Effectiveness source (NORMATIVE UPDATE 2026-06-13): ``qa_check_outcomes``
(FK-69 §69.15, verify-system-emitted, AG3-108), NOT ``story_metrics``.
Aggregation key: ``check_proposal_ref`` (the fc_check_proposals CHK-NNNN),
NOT the executed ``check_id`` (e.g. ``artifact.protocol``).

Canonical outcome mapping (FK-41 §41.6.7.1):
- ``triggered`` → true positive
- ``overridden`` → false positive
- ``clean`` → no finding (never counts as real find)

Sources:
- FK-41 §41.6.7 -- effectiveness tracking, auto-deactivation
- FK-41 §41.6.7.1 -- outcome mapping
- FK-41 §41.3.3 -- fc_check_proposals fields
- FK-69 §69.15 -- qa_check_outcomes table
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.core_types import CheckStatus
from agentkit.backend.failure_corpus.pattern import PatternRiskLevel
from agentkit.backend.failure_corpus.top import EffectivenessReport
from agentkit.backend.verify_system.stage_registry.records import CheckOutcome

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.backend.failure_corpus.check_proposal import CheckProposalRecord
    from agentkit.backend.state_backend.store.fc_check_proposal_repository import FcCheckProposalRepository
    from agentkit.backend.state_backend.store.fc_pattern_repository import FcPatternRepository
    from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor

# Auto-deactivation thresholds (FK-41 §41.6.7, FK-93 §93.11 "fixed in code")
_AUTO_DEACTIVATE_MIN_FP = 3  # fp > 3 (i.e., at least 4 false positives)


def _count_outcomes(
    outcomes: Sequence[object],
) -> tuple[int, int, int]:
    """Count true positives, false positives, and no-findings from outcome records.

    Args:
        outcomes: List of QACheckOutcomeRecord from qa_check_outcomes.

    Returns:
        Tuple of (true_positives, false_positives, no_findings).
    """
    tp = 0
    fp = 0
    nf = 0
    for rec in outcomes:
        # Access outcome attribute (QACheckOutcomeRecord is a dataclass)
        outcome = getattr(rec, "outcome", None)
        if outcome is CheckOutcome.TRIGGERED:
            tp += 1
        elif outcome is CheckOutcome.OVERRIDDEN:
            fp += 1
        elif outcome is CheckOutcome.CLEAN:
            nf += 1
    return tp, fp, nf


def _should_auto_deactivate(
    tp: int,
    fp: int,
    risk_level: str | None,
) -> bool:
    """Determine if a check should be auto-deactivated (FK-41 §41.6.7 exact).

    Auto-deactivation condition:
      true_positives_90d == 0 AND false_positives_90d > 3
      AND pattern risk_level != CRITICAL (exempt from auto-deactivation).

    Args:
        tp: True positive count in the window.
        fp: False positive count in the window.
        risk_level: PatternRiskLevel wire value of the parent pattern.

    Returns:
        True if the check should be auto-deactivated.
    """
    if risk_level == PatternRiskLevel.CRITICAL.value:
        return False
    return tp == 0 and fp > _AUTO_DEACTIVATE_MIN_FP


class CheckEffectivenessTracker:
    """Periodically recomputes effectiveness of all ACTIVE checks (FK-41 §41.6.7, AG3-078).

    Args:
        accessor: ProjectionAccessor for reading qa_check_outcomes.
        check_repo: Repository adapter for ``fc_check_proposals``.
        pattern_repo: Repository adapter for ``fc_patterns`` (for risk_level join).
        project_key: Project key (mandatory; all reads are project-bound).
    """

    def __init__(
        self,
        accessor: ProjectionAccessor,
        check_repo: FcCheckProposalRepository,
        pattern_repo: FcPatternRepository,
        project_key: str,
    ) -> None:
        self._accessor = accessor
        self._check_repo = check_repo
        self._pattern_repo = pattern_repo
        self._project_key = project_key

    def report_effectiveness(self, *, window_days: int = 90) -> EffectivenessReport:
        """Recompute effectiveness for all ACTIVE checks in the project.

        Reads qa_check_outcomes by check_proposal_ref (CHK-NNNN) for the window,
        aggregates tp/fp/nf, writes back to fc_check_proposals, auto-deactivates
        where condition met. Stateless: full 90d recount on every call.

        Missing history (no qa_check_outcomes rows for a check) is NOT treated as
        clean — absent history != clean (FAIL-CLOSED for deactivation logic).

        Args:
            window_days: Observation window in days (default 90).

        Returns:
            ``EffectivenessReport`` with updated and deactivated counts.
        """
        from agentkit.backend.telemetry.projection_accessor import ProjectionFilter, ProjectionKind

        active_checks = self._get_active_checks()

        now = datetime.now(UTC)
        updated = 0
        deactivated = 0

        for proposal in active_checks:
            # Read qa_check_outcomes for this check's proposal reference
            outcomes = self._accessor.read_projection(
                ProjectionKind.QA_CHECK_OUTCOMES,
                ProjectionFilter(
                    project_key=self._project_key,
                    check_proposal_ref=proposal.check_id,
                    since_days=window_days,
                ),
                _now=now,
            )

            tp, fp, nf = _count_outcomes(outcomes)

            # Get parent pattern risk level (intra-BC join)
            risk_level = self._get_pattern_risk_level(proposal.pattern_ref)

            # Determine if auto-deactivation applies
            auto_deactivate = _should_auto_deactivate(tp, fp, risk_level)

            # Build updated proposal
            new_status = CheckStatus.RETIRED if auto_deactivate else proposal.status

            updated_proposal = proposal.model_copy(
                update={
                    "status": new_status,
                    "true_positives_90d": tp,
                    "false_positives_90d": fp,
                    "no_findings_90d": nf,
                    "effectiveness_last_checked_at": now,
                }
            )
            self._check_repo.save(updated_proposal)
            updated += 1
            if auto_deactivate:
                deactivated += 1

        return EffectivenessReport(
            window_days=window_days,
            updated_count=updated,
            deactivated_count=deactivated,
        )

    def _get_active_checks(self) -> list[CheckProposalRecord]:
        """Return all ACTIVE check proposals for this project.

        Uses a single ``list_for_project`` repository query — no fixed-range
        scanning. Filters to ACTIVE status in memory after the single round-trip.
        """
        all_proposals = self._check_repo.list_for_project(self._project_key)
        return [p for p in all_proposals if p.status is CheckStatus.ACTIVE]

    def _get_pattern_risk_level(self, pattern_ref: str) -> str | None:
        """Get the risk_level of the parent pattern (intra-BC join).

        Args:
            pattern_ref: The pattern_ref (FP-NNNN) from the check proposal.

        Returns:
            The risk_level wire value (e.g. ``"critical"``), or ``None`` if not found.
        """
        pattern = self._pattern_repo.load(pattern_ref)
        if pattern is None:
            return None
        return pattern.risk_level.value


__all__ = [
    "CheckEffectivenessTracker",
]
