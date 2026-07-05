"""Closure execution-report writer.

Wraps the canonical ``record_closure_report`` mutation so closure-phase
code persists the canonical report and the export projection through a
named writer that lives next to the report records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.closure.execution_report.records import ExecutionReport
from agentkit.backend.state_backend.store import record_closure_report

if TYPE_CHECKING:
    from pathlib import Path


def write_execution_report(
    story_dir: Path,
    report: ExecutionReport,
    *,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> Path:
    """Persist the canonical closure report and export projection.

    Args:
        story_dir: Story artifacts directory.
        report: The execution report to persist.
        owner_session_id: (AG3-144, FK-91 §91.1a Rule 15) The caller's
            early-captured active ``run_ownership_records.owner_session_id``
            snapshot; re-verified at commit time under ``SELECT ... FOR UPDATE``.
        expected_ownership_epoch: The caller's early-captured
            ``ownership_epoch`` snapshot, re-verified the same way.
        projection_dir: Optional export projection directory.

    Returns:
        Path to the persisted closure report on disk.

    Raises:
        OwnershipFenceViolationError: (AG3-142 reuse) When the story's active
            ownership record no longer admits this exact snapshot at commit
            time -- nothing written.
    """

    return record_closure_report(
        story_dir,
        report,
        owner_session_id=owner_session_id,
        expected_ownership_epoch=expected_ownership_epoch,
        projection_dir=projection_dir,
    )


__all__ = ["ExecutionReport", "write_execution_report"]
