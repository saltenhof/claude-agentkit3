"""Sanctioned facade for canonical CCAG permission persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
    _require_postgres_control_plane_backend,
)

if TYPE_CHECKING:
    from agentkit.backend.governance.ccag.permission_records import (
        PermissionLeaseRecord,
        PermissionRequestRecord,
    )


def insert_request(record: PermissionRequestRecord) -> PermissionRequestRecord:
    """Insert and return one canonical request."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_postgres_control_plane_backend()
    row = _backend_module().insert_ccag_permission_request_global_row(
        mappers.permission_request_to_row(record)
    )
    return mappers.permission_request_row_to_record(row)


def load_request(request_id: str, now: str) -> PermissionRequestRecord | None:
    """Load one request with central lazy expiry."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_postgres_control_plane_backend()
    row = _backend_module().load_ccag_permission_request_global_row(request_id, now)
    return mappers.permission_request_row_to_record(row) if row is not None else None


def list_requests(
    project_key: str, story_id: str, run_id: str, now: str
) -> tuple[PermissionRequestRecord, ...]:
    """List run-scoped requests with central lazy expiry."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_postgres_control_plane_backend()
    rows = _backend_module().list_ccag_permission_request_rows_global(
        project_key, story_id, run_id, now
    )
    return tuple(mappers.permission_request_row_to_record(row) for row in rows)


def resolve_request(
    request_id: str, status: str, resolution: str, note: str, now: str
) -> PermissionRequestRecord | None:
    """Resolve one pending request and return its canonical row."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_postgres_control_plane_backend()
    row = _backend_module().resolve_ccag_permission_request_global_row(
        request_id, status, resolution, note, now
    )
    return mappers.permission_request_row_to_record(row) if row is not None else None


def insert_lease(record: PermissionLeaseRecord) -> PermissionLeaseRecord:
    """Insert and return one canonical lease."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_postgres_control_plane_backend()
    row = _backend_module().insert_ccag_permission_lease_global_row(
        mappers.permission_lease_to_row(record)
    )
    return mappers.permission_lease_row_to_record(row)


def load_lease(lease_id: str) -> PermissionLeaseRecord | None:
    """Load one canonical lease."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_postgres_control_plane_backend()
    row = _backend_module().load_ccag_permission_lease_global_row(lease_id)
    return mappers.permission_lease_row_to_record(row) if row is not None else None


def consume_lease(
    lease_id: str, now: str
) -> tuple[PermissionLeaseRecord | None, bool]:
    """Consume one lease use atomically."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_postgres_control_plane_backend()
    row, applied = _backend_module().consume_ccag_permission_lease_global_row(
        lease_id, now
    )
    record = mappers.permission_lease_row_to_record(row) if row is not None else None
    return record, applied
