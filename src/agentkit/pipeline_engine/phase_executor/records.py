"""Phase-executor records: immutable attempt data for one phase execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.story_context_manager.models import PhaseStatus

__all__ = ("AttemptRecord",)


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
