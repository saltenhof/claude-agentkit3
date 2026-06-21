"""Typed records for the control-plane authentication boundary."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StrategistCredentials(BaseModel):
    """Credentials submitted by the single strategist account."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    username: str
    password: str = Field(min_length=1)


class Session(BaseModel):
    """Server-side strategist session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    csrf_token: str
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime


class ProjectApiToken(BaseModel):
    """Persisted hashed token for one project-bound thin client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    token_id: str
    project_key: str
    label: str
    token_hash: str
    created_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
