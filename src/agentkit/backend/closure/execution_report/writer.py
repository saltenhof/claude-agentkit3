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
    projection_dir: Path | None = None,
) -> Path:
    """Persist the canonical closure report and export projection.

    Args:
        story_dir: Story artifacts directory.
        report: The execution report to persist.
        projection_dir: Optional export projection directory.

    Returns:
        Path to the persisted closure report on disk.
    """

    return record_closure_report(
        story_dir,
        report,
        projection_dir=projection_dir,
    )


__all__ = ["ExecutionReport", "write_execution_report"]
