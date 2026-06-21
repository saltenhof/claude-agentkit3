"""Guard-system records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = (
    "ConflictFreezeProofRecord",
    "GuardDecision",
    "GuardDecisionOutcome",
    "StoryExecutionLockRecord",
)


class GuardDecisionOutcome(StrEnum):
    """Canonical guard decision outcomes."""

    PASS = "PASS"
    WARNING = "WARNING"
    ERROR = "ERROR"


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


@dataclass(frozen=True)
class GuardDecision:
    """Append-only guard decision audit entity."""

    project_key: str
    story_id: str
    run_id: str
    flow_id: str
    guard_decision_id: str
    guard_key: str
    outcome: GuardDecisionOutcome
    decided_at: datetime
    node_id: str | None = None
    reason: str | None = None
    evidence_ref: str | None = None


@dataclass(frozen=True)
class ConflictFreezeProofRecord:
    """Persisted proof that a conflict-freeze has an official resolution path."""

    project_key: str
    story_id: str
    run_id: str
    proof_id: str
    activated_at: datetime
    blocked_principal: str
    resolution_service_path: str
