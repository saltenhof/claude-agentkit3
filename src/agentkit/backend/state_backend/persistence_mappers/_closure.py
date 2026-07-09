"""Story-closure push-sync row mappers."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ._common import _optional_iso_datetime, _OptionalString

if TYPE_CHECKING:
    from agentkit.backend.control_plane.push_sync import PushBarrierVerdict, PushFreshnessRecord



def push_freshness_record_to_row(record: PushFreshnessRecord) -> dict[str, Any]:
    """Convert a ``PushFreshnessRecord`` to a DB-insertable row dict."""

    return {
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "repo_id": record.repo_id,
        "last_reported_head_sha": record.last_reported_head_sha,
        "last_pushed_head_sha": record.last_pushed_head_sha,
        "last_reported_at": record.last_reported_at.isoformat(),
        "last_sync_point_id": record.last_sync_point_id,
        "last_command_id": record.last_command_id,
        "backlog": 1 if record.backlog else 0,
        "backlog_detail": record.backlog_detail,
    }



def push_freshness_row_to_record(row: dict[str, Any]) -> PushFreshnessRecord:
    """Convert a DB row dict to a ``PushFreshnessRecord``."""

    from typing import cast

    from agentkit.backend.control_plane.push_sync import (
        PushFreshnessRecord as _PushFreshnessRecord,
    )

    return _PushFreshnessRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        repo_id=str(row["repo_id"]),
        last_reported_head_sha=cast("_OptionalString", row.get("last_reported_head_sha")),
        last_pushed_head_sha=cast("_OptionalString", row.get("last_pushed_head_sha")),
        last_reported_at=datetime.fromisoformat(str(row["last_reported_at"])),
        last_sync_point_id=cast("_OptionalString", row.get("last_sync_point_id")),
        last_command_id=cast("_OptionalString", row.get("last_command_id")),
        backlog=bool(int(row["backlog"])),
        backlog_detail=cast("_OptionalString", row.get("backlog_detail")),
    )



def push_barrier_verdict_to_row(record: PushBarrierVerdict) -> dict[str, Any]:
    """Convert a ``PushBarrierVerdict`` to a DB-insertable row dict."""

    return {
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "boundary_type": record.boundary_type.value,
        "boundary_id": record.boundary_id,
        "repo_id": record.repo_id,
        "producer": record.producer,
        "boundary_epoch": record.boundary_epoch,
        "expected_head_sha": record.expected_head_sha,
        "server_head_sha": record.server_head_sha,
        "ownership_epoch": record.ownership_epoch,
        "status": record.status.value,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "resolved_at": (
            record.resolved_at.isoformat() if record.resolved_at is not None else None
        ),
        "status_detail": record.status_detail,
    }



def push_barrier_verdict_row_to_record(row: dict[str, Any]) -> PushBarrierVerdict:
    """Convert a DB row dict to a ``PushBarrierVerdict``."""

    from typing import cast

    from agentkit.backend.control_plane.push_sync import (
        PushBarrierVerdict as _PushBarrierVerdict,
    )
    from agentkit.backend.control_plane.push_sync import (
        PushBarrierVerdictStatus,
        SyncPointBarrierType,
    )

    return _PushBarrierVerdict(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        boundary_type=SyncPointBarrierType(str(row["boundary_type"])),
        boundary_id=str(row["boundary_id"]),
        repo_id=str(row["repo_id"]),
        producer=str(row["producer"]),
        boundary_epoch=int(row["boundary_epoch"]),
        expected_head_sha=cast("_OptionalString", row.get("expected_head_sha")),
        server_head_sha=cast("_OptionalString", row.get("server_head_sha")),
        ownership_epoch=int(row["ownership_epoch"]),
        status=PushBarrierVerdictStatus(str(row["status"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        resolved_at=_optional_iso_datetime(row.get("resolved_at")),
        status_detail=cast("_OptionalString", row.get("status_detail")),
    )
