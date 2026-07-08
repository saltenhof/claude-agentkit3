"""Flow-execution row projections for state backend mappers."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentkit.backend.phase_state_store.models import FlowExecution


def flow_execution_to_row(record: FlowExecution) -> dict[str, Any]:
    """Convert a ``FlowExecution`` to a DB-insertable row dict."""
    return {
        "story_id": record.story_id,
        "project_key": record.project_key,
        "run_id": record.run_id,
        "flow_id": record.flow_id,
        "level": record.level,
        "owner": record.owner,
        "parent_flow_id": record.parent_flow_id,
        "status": record.status,
        "current_node_id": record.current_node_id,
        "attempt_no": record.attempt_no,
        "started_at": record.started_at.isoformat(),
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
    }


def flow_execution_row_to_record(row: dict[str, Any]) -> FlowExecution:
    """Convert a DB row dict to a ``FlowExecution``."""
    from agentkit.backend.phase_state_store.models import FlowExecution as _FlowExecution

    return _FlowExecution(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        flow_id=str(row["flow_id"]),
        level=str(row["level"]),
        owner=str(row["owner"]),
        parent_flow_id=(
            str(row["parent_flow_id"]) if row["parent_flow_id"] is not None else None
        ),
        status=str(row["status"]),
        current_node_id=(
            str(row["current_node_id"]) if row["current_node_id"] is not None else None
        ),
        attempt_no=int(row["attempt_no"]),
        started_at=datetime.fromisoformat(str(row["started_at"])),
        finished_at=(
            datetime.fromisoformat(str(row["finished_at"]))
            if row["finished_at"] is not None
            else None
        ),
    )
