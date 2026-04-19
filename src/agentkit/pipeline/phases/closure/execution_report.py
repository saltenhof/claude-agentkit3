"""Compatibility wrapper for closure execution reports."""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.state_backend import ExecutionReport, record_closure_report


def write_execution_report(story_dir, report: ExecutionReport):
    """Persist the canonical closure report and export projection."""

    return record_closure_report(story_dir, report)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()
