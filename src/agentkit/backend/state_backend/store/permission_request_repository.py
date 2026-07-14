"""Postgres-backed adapter for the CCAG permission-request port."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.governance.ccag.permission_errors import (
    PermissionConflictError,
    PermissionNotFoundError,
)
from agentkit.backend.state_backend import ccag_permission_store

if TYPE_CHECKING:
    from agentkit.backend.governance.ccag.permission_records import (
        PermissionRequestRecord,
        PermissionRequestStatus,
        PermissionResolution,
    )


class StateBackendPermissionRequestRepository:
    """Implement canonical request persistence through the state facade."""

    def create(self, record: PermissionRequestRecord) -> PermissionRequestRecord:
        """Insert idempotently or reject a reused mismatching identity."""
        stored = ccag_permission_store.insert_request(record)
        if stored != record:
            raise PermissionConflictError(
                f"request_id {record.request_id!r} already has different content"
            )
        return stored

    def load(self, request_id: str) -> PermissionRequestRecord | None:
        """Read one request and lazily materialize expiry."""
        return ccag_permission_store.load_request(request_id, _now())

    def list_for_run(
        self, project_key: str, story_id: str, run_id: str
    ) -> tuple[PermissionRequestRecord, ...]:
        """Read a run-scoped inbox and lazily materialize expiry."""
        return ccag_permission_store.list_requests(
            project_key, story_id, run_id, _now()
        )

    def resolve(
        self,
        request_id: str,
        status: PermissionRequestStatus,
        resolution: PermissionResolution,
        decision_note: str,
    ) -> PermissionRequestRecord:
        """Resolve a pending request idempotently."""
        record = ccag_permission_store.resolve_request(
            request_id, status, resolution, decision_note, _now()
        )
        if record is None:
            raise PermissionNotFoundError(f"unknown request_id {request_id!r}")
        if record.status != status or record.resolution != resolution:
            raise PermissionConflictError(
                f"request_id {request_id!r} is already terminal as {record.status!r}"
            )
        return record


def _now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = ["StateBackendPermissionRequestRepository"]
