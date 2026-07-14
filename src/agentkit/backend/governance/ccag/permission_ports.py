"""Injected persistence ports for canonical CCAG permission state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agentkit.backend.governance.ccag.permission_records import (
        PermissionLeaseRecord,
        PermissionRequestRecord,
        PermissionRequestStatus,
        PermissionResolution,
    )


class PermissionRequestRepository(Protocol):
    """Persistence contract for canonical permission requests."""

    def create(self, record: PermissionRequestRecord) -> PermissionRequestRecord: ...
    def load(self, request_id: str) -> PermissionRequestRecord | None: ...
    def list_for_run(
        self, project_key: str, story_id: str, run_id: str
    ) -> tuple[PermissionRequestRecord, ...]: ...
    def resolve(
        self,
        request_id: str,
        status: PermissionRequestStatus,
        resolution: PermissionResolution,
        decision_note: str,
    ) -> PermissionRequestRecord: ...


class PermissionLeaseRepository(Protocol):
    """Persistence contract for canonical permission leases."""

    def create(self, record: PermissionLeaseRecord) -> PermissionLeaseRecord: ...
    def load(self, lease_id: str) -> PermissionLeaseRecord | None: ...
    def consume(self, lease_id: str) -> PermissionLeaseRecord: ...


__all__ = ["PermissionLeaseRepository", "PermissionRequestRepository"]
