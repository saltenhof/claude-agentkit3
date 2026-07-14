"""Frontend read models for cross-project takeover approvals."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TakeoverRepoPushStatus(BaseModel):
    """Pushed-state evidence for one repository."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str = Field(min_length=1)
    last_pushed_head_sha: str | None = None
    last_push_at: datetime | None = None
    push_lag_hint: str | None = None


class TakeoverApprovalRequest(BaseModel):
    """Exact v3 ``takeover_approval_request`` frontend entity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1)
    challenge_id: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    requested_by_principal: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    owner_session_id: str = Field(min_length=1)
    ownership_epoch: int = Field(ge=1)
    binding_version: int = Field(ge=1)
    phase: str = Field(min_length=1)
    last_api_contact_at: datetime | None = None
    open_operation_ids: list[str] = Field(default_factory=list)
    repo_push_status: list[TakeoverRepoPushStatus] = Field(default_factory=list)
    takeover_history_count: int = Field(ge=0)
    status: Literal["pending", "approved", "denied", "expired", "invalidated"]
    requested_at: datetime
    expires_at: datetime | None = None


class TakeoverChallengeNotice(BaseModel):
    """Owner-BC loss-corridor text linked to one stored challenge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge_id: str = Field(min_length=1)
    loss_corridor_notice_key: str = Field(min_length=1)
    loss_corridor_notice_text: str = Field(min_length=1)


class TakeoverApprovalsResponse(BaseModel):
    """Cross-project open approvals and their owner-BC notices."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approvals: list[TakeoverApprovalRequest] = Field(default_factory=list)
    challenges: list[TakeoverChallengeNotice] = Field(default_factory=list)


__all__ = [
    "TakeoverApprovalRequest",
    "TakeoverApprovalsResponse",
    "TakeoverChallengeNotice",
    "TakeoverRepoPushStatus",
]
