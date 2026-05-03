"""Guard-system records: central lock record for story-execution regime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ("StoryExecutionLockRecord",)


@dataclass(frozen=True)
class StoryExecutionLockRecord:
    """Central lock record for the active story-execution regime."""

    project_key: str
    story_id: str
    run_id: str
    lock_type: str
    status: str
    worktree_roots: tuple[str, ...]
    binding_version: str
    activated_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None = None
