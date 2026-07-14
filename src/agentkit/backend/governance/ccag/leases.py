"""Compatibility names for canonical central permission-lease records.

The former per-story SQLite writer/consumer was removed by AG3-131. Lease
creation and atomic consumption are backend-owned Postgres operations.
"""

from __future__ import annotations

from agentkit.backend.governance.ccag.permission_errors import (
    PermissionLeaseExhaustedError,
    PermissionLeaseExpiredError,
    PermissionNotFoundError,
)
from agentkit.backend.governance.ccag.permission_records import PermissionLeaseRecord

LeaseExhaustedError = PermissionLeaseExhaustedError
LeaseExpiredError = PermissionLeaseExpiredError
LeaseNotFoundError = PermissionNotFoundError
PermissionLease = PermissionLeaseRecord

__all__ = [
    "LeaseExhaustedError",
    "LeaseExpiredError",
    "LeaseNotFoundError",
    "PermissionLease",
]
