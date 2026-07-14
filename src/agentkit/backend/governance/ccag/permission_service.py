"""Governance owner for canonical CCAG permission requests and leases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from agentkit.backend.governance.ccag.permission_errors import PermissionConflictError
from agentkit.backend.governance.ccag.permission_records import (
    PermissionLeaseRecord,
    PermissionRequestRecord,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.governance.ccag.permission_commands import (
        GrantPermissionLeaseCommand,
        OpenPermissionRequestCommand,
        ResolvePermissionRequestCommand,
    )
    from agentkit.backend.governance.ccag.permission_ports import (
        PermissionLeaseRepository,
        PermissionRequestRepository,
    )


class PermissionService:
    """Apply permission lifecycle rules through injected persistence ports."""

    def __init__(
        self,
        requests: PermissionRequestRepository,
        leases: PermissionLeaseRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._requests = requests
        self._leases = leases
        self._clock = clock or (lambda: datetime.now(UTC))

    def open(self, command: OpenPermissionRequestCommand) -> PermissionRequestRecord:
        """Create a pending request in the central owner."""
        now = self._clock()
        return self._requests.create(
            PermissionRequestRecord(
                **command.model_dump(exclude={"ttl_seconds"}),
                status="pending",
                requested_at=now,
                expires_at=now + timedelta(seconds=command.ttl_seconds),
            )
        )

    def read(self, request_id: str) -> PermissionRequestRecord | None:
        """Read one request, lazily materializing expiry."""
        return self._requests.load(request_id)

    def list_for_run(
        self, project_key: str, story_id: str, run_id: str
    ) -> tuple[PermissionRequestRecord, ...]:
        """Read a run-scoped request inbox, lazily materializing expiry."""
        return self._requests.list_for_run(project_key, story_id, run_id)

    def resolve(
        self, command: ResolvePermissionRequestCommand
    ) -> PermissionRequestRecord:
        """Apply a human approve/deny decision without auto-resume."""
        status: Literal["approved", "denied"] = (
            "approved" if command.resolution == "approved" else "denied"
        )
        return self._requests.resolve(
            command.request_id, status, command.resolution, command.decision_note
        )

    def grant(self, command: GrantPermissionLeaseCommand) -> PermissionLeaseRecord:
        """Create only a lease from an approved request; never resume the run."""
        request = self._requests.load(command.request_ref)
        if request is None or request.status != "approved":
            raise PermissionConflictError("lease grant requires an approved request")
        now = self._clock()
        return self._leases.create(
            PermissionLeaseRecord(
                lease_id=command.lease_id, request_ref=request.request_id,
                project_key=request.project_key, story_id=request.story_id,
                run_id=request.run_id, principal_type=request.principal_type,
                tool_name=request.tool_name, operation_class=request.operation_class,
                path_classes=request.path_classes,
                request_fingerprint=request.request_fingerprint,
                max_uses=command.max_uses, issued_at=now,
                expires_at=now + timedelta(seconds=command.ttl_seconds),
            )
        )

    def consume(self, lease_id: str) -> PermissionLeaseRecord:
        """Atomically consume one permitted lease use."""
        return self._leases.consume(lease_id)

    def read_lease(self, lease_id: str) -> PermissionLeaseRecord | None:
        """Read one canonical permission lease."""
        return self._leases.load(lease_id)
