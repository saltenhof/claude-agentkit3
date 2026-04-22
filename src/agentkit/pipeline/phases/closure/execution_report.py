"""Compatibility wrapper for closure execution reports."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.state_backend import ExecutionReport, record_closure_report

if TYPE_CHECKING:
    from pathlib import Path


def write_execution_report(
    story_dir: Path,
    report: ExecutionReport,
    *,
    projection_dir: Path | None = None,
) -> Path:
    """Persist the canonical closure report and export projection."""

    return record_closure_report(
        story_dir,
        report,
        projection_dir=projection_dir,
    )


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


__all__ = ["ExecutionReport", "write_execution_report"]
