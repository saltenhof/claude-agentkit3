"""Harness edge-command persistence store."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
    _require_control_plane_backend,
)

if TYPE_CHECKING:
    from datetime import datetime


def insert_edge_command_record_global(record: Any) -> None:
    """Strictly insert one edge-command row."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.insert_edge_command_record_global_row(
        mappers.edge_command_record_to_row(record),
    )


def commission_edge_command_record_global(record: Any) -> bool:
    """Atomically insert one edge-command row if absent."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.commission_edge_command_record_global_row(
            mappers.edge_command_record_to_row(record),
        )
    )


def load_edge_command_record_global(command_id: str) -> Any | None:
    """Load one edge-command record by ``command_id``, or ``None``."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_edge_command_record_global_row(command_id)
    if row is None:
        return None
    return mappers.edge_command_row_to_record(row)


def list_and_ack_open_edge_command_records_global(
    *,
    project_key: str,
    run_id: str,
    session_id: str,
    delivered_at: datetime,
) -> tuple[Any, ...]:
    """Return and acknowledge the session's open edge commands."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_and_ack_open_edge_command_records_global_row(
        project_key=project_key,
        run_id=run_id,
        session_id=session_id,
        delivered_at=delivered_at.isoformat(),
    )
    return tuple(mappers.edge_command_row_to_record(row) for row in rows)


def supersede_open_edge_command_global(
    *,
    command_id: str,
    completed_at: datetime,
    result_payload: dict[str, object],
) -> bool:
    """Terminalize an open edge command superseded by a newer boundary epoch."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.supersede_open_edge_command_global_row(
            command_id=command_id,
            completed_at=completed_at.isoformat(),
            result_payload_json=mappers.dump_json(result_payload),
        )
    )


__all__ = [
    "insert_edge_command_record_global",
    "commission_edge_command_record_global",
    "load_edge_command_record_global",
    "list_and_ack_open_edge_command_records_global",
    "supersede_open_edge_command_global",
]
