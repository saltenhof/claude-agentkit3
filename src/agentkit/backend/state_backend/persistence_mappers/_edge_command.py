"""Harness edge-command row mappers."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ._common import _optional_iso_datetime, _OptionalString, cast_json_record, dump_json, load_json

if TYPE_CHECKING:
    from agentkit.backend.control_plane.records import EdgeCommandRecord



def edge_command_record_to_row(record: EdgeCommandRecord) -> dict[str, Any]:
    """Convert an ``EdgeCommandRecord`` to a DB-insertable row dict."""

    return {
        "command_id": record.command_id,
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "session_id": record.session_id,
        "command_kind": record.command_kind,
        "payload_json": dump_json(record.payload),
        "status": record.status,
        "ownership_epoch": record.ownership_epoch,
        "created_at": record.created_at.isoformat(),
        "delivered_at": (
            record.delivered_at.isoformat() if record.delivered_at is not None else None
        ),
        "completed_at": (
            record.completed_at.isoformat() if record.completed_at is not None else None
        ),
        "result_op_id": record.result_op_id,
        "result_type": record.result_type,
        "result_payload_json": (
            dump_json(record.result_payload) if record.result_payload is not None else None
        ),
    }



def edge_command_row_to_record(row: dict[str, Any]) -> EdgeCommandRecord:
    """Convert a DB row dict to an ``EdgeCommandRecord``."""

    from typing import cast

    from agentkit.backend.control_plane.records import (
        EdgeCommandRecord as _EdgeCommandRecord,
    )

    result_payload_json = row.get("result_payload_json")
    return _EdgeCommandRecord(
        command_id=str(row["command_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        session_id=str(row["session_id"]),
        command_kind=str(row["command_kind"]),
        payload=cast_json_record(load_json(row["payload_json"], {})),
        status=str(row["status"]),
        ownership_epoch=int(row["ownership_epoch"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        delivered_at=_optional_iso_datetime(row.get("delivered_at")),
        completed_at=_optional_iso_datetime(row.get("completed_at")),
        result_op_id=cast("_OptionalString", row.get("result_op_id")),
        result_type=cast("_OptionalString", row.get("result_type")),
        result_payload=(
            cast_json_record(load_json(cast("str", result_payload_json), {}))
            if result_payload_json is not None
            else None
        ),
    )
