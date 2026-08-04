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

    #: Both values are bearer secrets: whoever holds ``session_id`` IS the
    #: session, and ``csrf_token`` guards its mutating use. ``repr=False`` keeps
    #: them out of tracebacks, logs and telemetry -- the same channel that
    #: already leaked the password hash. The values stay reachable as
    #: attributes; only their DISPLAY is suppressed.
    session_id: str = Field(repr=False)
    csrf_token: str = Field(repr=False)
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime


class ProjectApiToken(BaseModel):
    """Persisted hashed token for one project-bound thin client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    token_id: str
    project_key: str
    label: str
    #: The hash is a verifier, not a public value: it belongs in no traceback,
    #: log or telemetry line. Same channel, same rule as ``Session`` above.
    token_hash: str = Field(repr=False)
    created_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
