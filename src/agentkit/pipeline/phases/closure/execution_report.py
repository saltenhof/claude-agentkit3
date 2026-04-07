"""Execution report for completed stories.

Writes a ``closure.json`` summarising the story execution:
phases executed, status, timestamps, and any warnings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.project_ops.shared.file_ops import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class ExecutionReport:
    """Summary of a completed story execution.

    Args:
        story_id: The story identifier.
        story_type: String representation of the story type.
        status: Overall outcome (``"completed"`` or
            ``"completed_with_warnings"``).
        phases_executed: Ordered tuple of phase names that ran.
        started_at: ISO 8601 timestamp when execution began.
        completed_at: ISO 8601 timestamp when execution finished.
        issue_closed: Whether the GitHub issue was closed.
        warnings: Any warnings accumulated during closure.
    """

    story_id: str
    story_type: str
    status: str
    phases_executed: tuple[str, ...]
    started_at: str | None = None
    completed_at: str | None = None
    issue_closed: bool = False
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Serialize to dict for JSON persistence.

        Returns:
            A JSON-serialisable dictionary.
        """
        return {
            "story_id": self.story_id,
            "story_type": self.story_type,
            "status": self.status,
            "phases_executed": list(self.phases_executed),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "issue_closed": self.issue_closed,
            "warnings": list(self.warnings),
        }


def write_execution_report(story_dir: Path, report: ExecutionReport) -> Path:
    """Write ``closure.json`` to the story directory.

    Uses atomic write to guarantee crash safety.

    Args:
        story_dir: Root directory for this story's artifacts.
        report: The execution report to persist.

    Returns:
        Absolute path to the written ``closure.json`` file.
    """
    path = story_dir / "closure.json"
    content = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    atomic_write_text(path, content)
    return path


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string.

    Returns:
        ISO 8601 formatted timestamp.
    """
    return datetime.now(tz=UTC).isoformat()
