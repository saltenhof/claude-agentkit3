"""Typed read models for the external Multi-LLM Hub adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HubBackendName = Literal["chatgpt", "gemini", "grok", "qwen", "kimi"]
HubSessionStatus = Literal["active", "released", "expired"]
HubBackendStatus = Literal["healthy", "degraded", "unavailable"]
HubMessageRole = Literal["user", "assistant"]
HubMessageStatus = Literal["ok", "pending", "error"]
HubHealthStatus = Literal["ok", "degraded", "down"]


class HubHolder(BaseModel):
    """Session holder occupying a backend slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    owner: str
    description: str


class HubSession(BaseModel):
    """Read model for one Hub session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    owner: str
    description: str
    llms: list[HubBackendName]
    status: HubSessionStatus
    created_at: datetime
    last_activity: datetime
    resumable: bool


class HubBackendMetric(BaseModel):
    """Backend metric card for the Hub cockpit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: HubBackendName
    label: str
    status: HubBackendStatus
    slots_total: int = Field(ge=0)
    slots_in_use: int = Field(ge=0)
    sends: int = Field(ge=0)
    responses: int = Field(ge=0)
    errors: int = Field(ge=0)
    avg_response_ms: int | None = None
    holders: list[HubHolder]


class HubMessage(BaseModel):
    """Message read model returned by send proxy operations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    session_id: str
    backend: HubBackendName | None
    role: HubMessageRole
    text: str
    at: datetime
    status: HubMessageStatus | None = None


class HubHealth(BaseModel):
    """Health response from the external Hub."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: HubHealthStatus
    version: str | None = None
    backends: dict[HubBackendName, Literal["ok", "error"]]
    persistence: Literal["ok", "error"]
    uptime_ms: int = Field(ge=0)


class HubSessionLease(BaseModel):
    """Session lease returned by acquire and resume."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    token: str
    llms: list[HubBackendName]
    slots: dict[HubBackendName, int]
