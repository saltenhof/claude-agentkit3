"""Governance-runtime row mappers."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ._common import dump_json, load_json

if TYPE_CHECKING:
    from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord



def execution_lock_to_row(record: StoryExecutionLockRecord) -> dict[str, Any]:
    """Convert a ``StoryExecutionLockRecord`` to a DB-insertable row dict."""

    return {
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "lock_type": record.lock_type,
        "status": record.status,
        "worktree_roots_json": dump_json(list(record.worktree_roots)),
        "binding_version": record.binding_version,
        "activated_at": record.activated_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "deactivated_at": (
            record.deactivated_at.isoformat()
            if record.deactivated_at is not None
            else None
        ),
    }



def execution_lock_row_to_record(row: dict[str, Any]) -> StoryExecutionLockRecord:
    """Convert a DB row dict to a ``StoryExecutionLockRecord``."""


    from agentkit.backend.governance.guard_system.records import (
        StoryExecutionLockRecord as _StoryExecutionLockRecord,
    )

    deactivated_at_raw = row["deactivated_at"]
    return _StoryExecutionLockRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        lock_type=str(row["lock_type"]),
        status=str(row["status"]),
        worktree_roots=tuple(load_json(row["worktree_roots_json"], [])),
        binding_version=str(row["binding_version"]),
        activated_at=datetime.fromisoformat(str(row["activated_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        deactivated_at=(
            datetime.fromisoformat(str(deactivated_at_raw))
            if deactivated_at_raw is not None
            else None
        ),
    )
