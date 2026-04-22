"""Pydantic request/response models for the control plane."""

from __future__ import annotations

import uuid
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


class _ControlPlaneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")
    source_component: str = Field(min_length=1, default="project_edge_client")


class PhaseMutationRequest(_ControlPlaneRequest):
    """Canonical request payload for a phase mutation."""

    principal_type: str = Field(min_length=1)
    worktree_roots: list[str] = Field(min_length=1)
    detail: dict[str, object] = Field(default_factory=dict)


class ClosureCompleteRequest(_ControlPlaneRequest):
    """Canonical request payload for closure completion."""

    detail: dict[str, object] = Field(default_factory=dict)


class ProjectEdgeSyncRequest(BaseModel):
    """Canonical request payload for a bounded project-edge sync."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    op_id: str = Field(default_factory=lambda: f"op-{uuid.uuid4().hex}")
    freshness_class: Literal["baseline_read", "guarded_read", "mutation"] = (
        "guarded_read"
    )


class EdgePointer(BaseModel):
    """Atomic pointer to one locally materializable edge bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    export_version: str
    operating_mode: Literal["ai_augmented", "story_execution", "binding_invalid"]
    bundle_dir: str
    sync_after: datetime
    freshness_class: Literal["baseline_read", "guarded_read", "mutation"]
    generated_at: datetime


class SessionRunBindingView(BaseModel):
    """Serializable session binding materialized into the edge bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    project_key: str
    story_id: str
    run_id: str
    principal_type: str
    worktree_roots: list[str]
    binding_version: str
    operating_mode: Literal["ai_augmented", "story_execution", "binding_invalid"]


class StoryExecutionLockView(BaseModel):
    """Serializable lock state materialized into the edge bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    story_id: str
    run_id: str
    lock_type: str
    status: Literal["ACTIVE", "INACTIVE", "INVALID"]
    worktree_roots: list[str]
    binding_version: str
    activated_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None = None


class EdgeBundle(BaseModel):
    """Complete bundle that the local Project Edge Client publishes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    current: EdgePointer
    session: SessionRunBindingView | None = None
    lock: StoryExecutionLockView
    tombstone_worktree_roots: list[str] = Field(default_factory=list)


class ControlPlaneMutationResult(BaseModel):
    """Shared response body for mutations, sync, and op reconciliation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["committed", "replayed", "synced"]
    op_id: str
    operation_kind: str
    run_id: str | None = None
    phase: str | None = None
    edge_bundle: EdgeBundle
