"""Stage-registry records: queryable QA stage and finding projections."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = (
    "CheckOutcome",
    "QACheckOutcomeRecord",
    "QAFindingRecord",
    "QAStageResultRecord",
)


class CheckOutcome(StrEnum):
    """Outcome enum for every executed QA check (FK-69 §69.15).

    Values:
        triggered: The check produced at least one finding (non-PASS).
        clean: The check passed with no finding (PASS).
        overridden: The check outcome was suppressed by an override.
    """

    TRIGGERED = "triggered"
    CLEAN = "clean"
    OVERRIDDEN = "overridden"


@dataclass(frozen=True)
class QAStageResultRecord:
    """Queryable outcome of one QA stage for a single verify attempt."""

    project_key: str
    story_id: str
    run_id: str
    attempt_no: int
    stage_id: str
    layer: str
    producer_component: str
    status: str
    blocking: bool
    total_checks: int
    failed_checks: int
    warning_checks: int
    artifact_id: str
    recorded_at: datetime


@dataclass(frozen=True)
class QACheckOutcomeRecord:
    """Per-check outcome row in ``qa_check_outcomes`` (FK-69 §69.15).

    Records the result of every individual check executed by verify-system.
    Unlike ``qa_findings`` (non-PASS only), this table records a row for
    EVERY executed check — including clean (PASS) checks and overridden
    checks.

    Schema-Owner: verify-system.
    DB-Owner: telemetry-and-events via ProjectionAccessor.

    Attributes:
        project_key: Mandatory project scope (FK-69 §69.2 rule 2).
        story_id: Story display-ID.
        run_id: Run-correlation ID.
        stage_id: Executing stage identifier (e.g. ``artifact.protocol``,
            ``qa_review``). Mandatory identity field — the same ``check_id``
            may run in multiple stages.
        attempt_no: 1-based QA-remediation attempt. Mandatory identity field
            — the same ``check_id`` reruns across remediation rounds.
        check_id: Executed-check identifier. NOT a ``fc_check_proposals``
            CHK-NNNN proposal ID.
        outcome: One of :class:`CheckOutcome` (triggered/clean/overridden).
        occurred_at: UTC timestamp of check execution.
        check_proposal_ref: Optional reference to ``fc_check_proposals.check_id``
            (CHK-NNNN); set ONLY when the check originated from a proposal.
        override_id: Optional correlation to the globally unique
            ``OverrideRecord.override_id`` that caused an ``overridden``
            outcome. NULL for triggered/clean rows.
    """

    project_key: str
    story_id: str
    run_id: str
    stage_id: str
    attempt_no: int
    check_id: str
    outcome: CheckOutcome
    occurred_at: datetime
    check_proposal_ref: str | None = None
    override_id: str | None = None


@dataclass(frozen=True)
class QAFindingRecord:
    """Queryable projection of one QA finding for a single verify attempt."""

    project_key: str
    story_id: str
    run_id: str
    attempt_no: int
    stage_id: str
    finding_id: str
    check_id: str
    status: str
    severity: str
    blocking: bool
    source_component: str
    artifact_id: str
    occurred_at: datetime
    category: str | None = None
    reason: str | None = None
    description: str | None = None
    detail: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
