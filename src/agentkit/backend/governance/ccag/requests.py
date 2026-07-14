"""Compatibility names for canonical central permission-request records.

The former SQLite writer was removed by AG3-131. Local request databases are
not a persistence option; the backend-owned service and Postgres repository are
the only canonical lifecycle path.
"""

from __future__ import annotations

from agentkit.backend.governance.ccag.permission_records import PermissionRequestRecord

DEFAULT_TTL_SECONDS: int = 1800
PermissionRequest = PermissionRequestRecord

__all__ = ["DEFAULT_TTL_SECONDS", "PermissionRequest"]
