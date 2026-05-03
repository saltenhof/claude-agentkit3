"""Control-plane records: session-run binding and operation records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ("ControlPlaneOperationRecord", "SessionRunBindingRecord")


@dataclass(frozen=True)
class SessionRunBindingRecord:
    """Central session-to-run binding used for operating mode resolution."""

    session_id: str
    project_key: str
    story_id: str
    run_id: str
    principal_type: str
    worktree_roots: tuple[str, ...]
    binding_version: str
    updated_at: datetime


@dataclass(frozen=True)
class ControlPlaneOperationRecord:
    """Idempotent mutation record for one control-plane operation."""

    op_id: str
    project_key: str
    story_id: str
    run_id: str | None
    session_id: str | None
    operation_kind: str
    phase: str | None
    status: str
    response_payload: dict[str, object]
    created_at: datetime
    updated_at: datetime
