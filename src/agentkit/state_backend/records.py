"""Canonical runtime record types for the state backend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.story_context_manager.models import PhaseStatus


@dataclass(frozen=True)
class AttemptRecord:
    """Immutable record of a single phase execution attempt."""

    attempt_id: str
    phase: str
    entered_at: datetime
    exit_status: PhaseStatus | None = None
    guard_evaluations: tuple[dict[str, object], ...] = ()
    artifacts_produced: tuple[str, ...] = ()
    outcome: str | None = None
    yield_status: str | None = None
    resume_trigger: str | None = None


@dataclass(frozen=True)
class ExecutionReport:
    """Summary of a completed story execution."""

    story_id: str
    story_type: str
    status: str
    phases_executed: tuple[str, ...]
    started_at: str | None = None
    completed_at: str | None = None
    issue_closed: bool = False
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Serialize to the canonical export shape."""

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
