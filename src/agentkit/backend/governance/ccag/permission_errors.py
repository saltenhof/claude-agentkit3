"""Named fail-closed CCAG permission persistence faults."""

from __future__ import annotations


class PermissionStateError(RuntimeError):
    """Base fault for canonical permission state operations."""


class PermissionConflictError(PermissionStateError):
    """A request conflicts with the current canonical state."""


class PermissionNotFoundError(PermissionStateError):
    """A referenced canonical permission entity does not exist."""


class PermissionLeaseExhaustedError(PermissionStateError):
    """A permission lease has no remaining uses."""


class PermissionLeaseExpiredError(PermissionStateError):
    """A permission lease is past its expiry instant."""


__all__ = [
    "PermissionConflictError",
    "PermissionLeaseExhaustedError",
    "PermissionLeaseExpiredError",
    "PermissionNotFoundError",
    "PermissionStateError",
]
