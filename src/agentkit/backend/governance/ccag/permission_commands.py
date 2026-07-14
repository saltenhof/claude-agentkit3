"""Typed commands accepted by the canonical CCAG permission service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OpenPermissionRequestCommand(BaseModel):
    """Open one audit-ready permission request."""

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
    ttl_seconds: int = Field(default=1800, ge=1)


class ResolvePermissionRequestCommand(BaseModel):
    """Record a human decision without resuming the run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    resolution: Literal["approved", "denied"]
    decision_note: str = ""


class GrantPermissionLeaseCommand(BaseModel):
    """Grant a scoped lease from an approved request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lease_id: str = Field(min_length=1)
    request_ref: str = Field(min_length=1)
    max_uses: int = Field(default=1, ge=1)
    ttl_seconds: int = Field(default=1800, ge=1)


__all__ = [
    "GrantPermissionLeaseCommand",
    "OpenPermissionRequestCommand",
    "ResolvePermissionRequestCommand",
]
