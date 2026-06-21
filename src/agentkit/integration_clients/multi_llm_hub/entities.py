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
    backend: HubBackendName | None = None
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


class HubBackendSessionStats(BaseModel):
    """Per-LLM post-hoc stats for one Hub session (FK-25 §25.5.4).

    Read-only verification surface the fine-design adapter consumes after a
    discussion to assert each acquired LLM actually participated (>= 1 answer)
    and that the session was correctly released. NO enforcement logic lives in
    the model -- it is a typed fact carrier (ARCH-41).

    Attributes:
        backend: The LLM backend this row describes.
        message_count: Number of messages the backend exchanged this session.
        answered: Whether the backend produced at least one answer (>= 1
            assistant response). FK-25 §25.5.4: a 0-answer acquired LLM is a
            fail-closed abort upstream.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: HubBackendName
    message_count: int = Field(ge=0)
    answered: bool


class HubSessionStats(BaseModel):
    """Post-hoc ``llm_session_stats`` read model for one Hub session (FK-25 §25.5.4).

    The AK3-side consume surface for the external Hub's ``llm_session_stats``
    MCP tool. Read-only: it carries per-LLM participation + the session/release
    status so the fine-design adapter can (a) abort fail-closed on a 0-answer
    LLM and (b) write a telemetry WARNING when a session was not correctly
    released (SEVERITY-semantics).

    Attributes:
        session_id: The session these stats describe.
        status: The session lifecycle status (``active`` / ``released`` /
            ``expired``).
        released: Whether the session was correctly released. ``False`` (e.g. a
            still-``active`` or ``expired`` session after the discussion) drives
            the FK-25 §25.5.4 release WARNING.
        backends: Per-LLM stats for every acquired backend.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    status: HubSessionStatus
    released: bool
    backends: list[HubBackendSessionStats]
