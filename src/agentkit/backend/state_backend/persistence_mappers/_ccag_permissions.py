"""Record-row mappers for central CCAG permission state."""

from __future__ import annotations

import json
from typing import Any

from agentkit.backend.governance.ccag.permission_records import (
    PermissionLeaseRecord,
    PermissionRequestRecord,
)


def permission_request_to_row(record: PermissionRequestRecord) -> dict[str, Any]:
    """Map a canonical permission request to a driver-neutral row."""
    row = record.model_dump(mode="json")
    row["path_classes"] = json.dumps(row["path_classes"], sort_keys=True)
    return row


def permission_request_row_to_record(row: dict[str, Any]) -> PermissionRequestRecord:
    """Map one database row to a canonical permission request."""
    payload = dict(row)
    payload["path_classes"] = _path_classes(payload["path_classes"])
    return PermissionRequestRecord.model_validate(payload)


def permission_lease_to_row(record: PermissionLeaseRecord) -> dict[str, Any]:
    """Map a canonical permission lease to a driver-neutral row."""
    row = record.model_dump(mode="json")
    row["path_classes"] = json.dumps(row["path_classes"], sort_keys=True)
    return row


def permission_lease_row_to_record(row: dict[str, Any]) -> PermissionLeaseRecord:
    """Map one database row to a canonical permission lease."""
    payload = dict(row)
    payload["path_classes"] = _path_classes(payload["path_classes"])
    return PermissionLeaseRecord.model_validate(payload)


def _path_classes(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError("path_classes must be a JSON string array")
    return tuple(raw)


__all__ = [
    "permission_lease_row_to_record",
    "permission_lease_to_row",
    "permission_request_row_to_record",
    "permission_request_to_row",
]
