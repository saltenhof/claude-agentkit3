"""Canonical CCAG permission request and lease records."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PermissionRequestStatus = Literal["pending", "approved", "denied", "expired"]
PermissionResolution = Literal["approved", "denied"]


class PermissionRequestRecord(BaseModel):
    """Canonical central permission-request record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    principal_type: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    operation_class: str = Field(min_length=1)
    path_classes: tuple[str, ...] = Field(min_length=1)
    request_fingerprint: str = Field(min_length=1)
    status: PermissionRequestStatus
    requested_at: datetime
    expires_at: datetime
    resolution: PermissionResolution | None = None
    decided_at: datetime | None = None
    decision_note: str = ""


class PermissionLeaseRecord(BaseModel):
    """Canonical central scoped permission-lease record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lease_id: str = Field(min_length=1)
    request_ref: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    principal_type: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    operation_class: str = Field(min_length=1)
    path_classes: tuple[str, ...] = Field(min_length=1)
    request_fingerprint: str = Field(min_length=1)
    max_uses: int = Field(default=1, ge=1)
    consumed: int = Field(default=0, ge=0)
    issued_at: datetime
    expires_at: datetime

    @property
    def available(self) -> bool:
        """Return whether the lease still has an unused grant."""
        return self.consumed < self.max_uses


__all__ = [
    "PermissionLeaseRecord",
    "PermissionRequestRecord",
    "PermissionRequestStatus",
    "PermissionResolution",
]
