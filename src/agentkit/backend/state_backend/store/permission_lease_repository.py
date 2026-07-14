"""Postgres-backed adapter for the CCAG permission-lease port."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.governance.ccag.permission_errors import (
    PermissionConflictError,
    PermissionLeaseExhaustedError,
    PermissionLeaseExpiredError,
    PermissionNotFoundError,
)
from agentkit.backend.state_backend import ccag_permission_store

if TYPE_CHECKING:
    from agentkit.backend.governance.ccag.permission_records import PermissionLeaseRecord


class StateBackendPermissionLeaseRepository:
    """Implement canonical lease persistence through the state facade."""

    def create(self, record: PermissionLeaseRecord) -> PermissionLeaseRecord:
        """Insert idempotently or reject a reused mismatching identity."""
        stored = ccag_permission_store.insert_lease(record)
        if stored != record:
            raise PermissionConflictError(
                f"lease_id {record.lease_id!r} already has different content"
            )
        return stored

    def load(self, lease_id: str) -> PermissionLeaseRecord | None:
        """Load one canonical lease."""
        return ccag_permission_store.load_lease(lease_id)

    def consume(self, lease_id: str) -> PermissionLeaseRecord:
        """Atomically consume one use or raise a named terminal fault."""
        now = datetime.now(UTC)
        record, applied = ccag_permission_store.consume_lease(
            lease_id, now.isoformat()
        )
        if record is None:
            raise PermissionNotFoundError(f"unknown lease_id {lease_id!r}")
        if record.expires_at <= now:
            raise PermissionLeaseExpiredError(f"lease_id {lease_id!r} is expired")
        if not applied:
            raise PermissionLeaseExhaustedError(f"lease_id {lease_id!r} is exhausted")
        return record


__all__ = ["StateBackendPermissionLeaseRepository"]
