"""Control-plane port for the database-lifetime single-writer fence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord


class ControlPlaneWriterAlreadyActiveError(RuntimeError):
    """Raised when another process already owns the database writer lease."""


class ControlPlaneWriterLeaseLostError(RuntimeError):
    """Raised when the owning database session is no longer usable."""


class ControlPlaneWriterLease(Protocol):
    """Lifetime fence held by the one active control-plane writer process."""

    def assert_held(self) -> None:
        """Fail closed when the lease session has been lost."""

    def bind_identity(self, identity: BackendInstanceIdentityRecord) -> None:
        """Bind the immutable boot identity owned by this lease."""

    def request_scope(self) -> AbstractContextManager[None]:
        """Fence one accepted request until it has fully returned."""

    def quiesce_requests(self) -> None:
        """Reject new requests and wait for every accepted request to return."""

    def release(self) -> None:
        """Release the lease and its reserved connection idempotently."""


__all__ = [
    "ControlPlaneWriterAlreadyActiveError",
    "ControlPlaneWriterLease",
    "ControlPlaneWriterLeaseLostError",
]
