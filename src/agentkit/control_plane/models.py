"""Pydantic request/response models for the control plane."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agentkit.telemetry.events import EventType


class TelemetryEventIngestRequest(BaseModel):
    """Canonical request payload for one telemetry ingest call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    event_type: EventType
    occurred_at: datetime
    source_component: str = Field(min_length=1)
    severity: Literal["debug", "info", "warning", "error", "critical"] = "info"
    event_id: str | None = None
    phase: str | None = None
    flow_id: str | None = None
    node_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class TelemetryEventAccepted(BaseModel):
    """HTTP response body for a successfully ingested telemetry event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["accepted"] = "accepted"
    event_id: str
