"""Stage-registry records: queryable QA stage and finding projections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ("QAFindingRecord", "QAStageResultRecord")


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
