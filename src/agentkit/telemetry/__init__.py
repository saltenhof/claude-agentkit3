"""Telemetry subsystem -- events, emitters, storage, metrics, and projections.

Re-exports the public API for convenient access:

    from agentkit.telemetry import Event, EventType, MemoryEmitter
    from agentkit.telemetry import ProjectionAccessor, ProjectionKind
"""

from __future__ import annotations

from agentkit.telemetry.emitters import (
    EventEmitter,
    MemoryEmitter,
    NullEmitter,
)
from agentkit.telemetry.errors import ProjectionRecordTypeMismatchError
from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.metrics import PipelineMetrics, compute_pipeline_metrics
from agentkit.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
    PurgeResult,
)
from agentkit.telemetry.projection_records import (
    ProjectionRecord,
)
from agentkit.telemetry.storage import StateBackendEmitter

__all__ = [
    "Event",
    "EventEmitter",
    "EventType",
    "MemoryEmitter",
    "NullEmitter",
    "PipelineMetrics",
    "ProjectionAccessor",
    "ProjectionFilter",
    "ProjectionKind",
    "ProjectionRecord",
    "ProjectionRecordTypeMismatchError",
    "PurgeResult",
    "StateBackendEmitter",
    "compute_pipeline_metrics",
]
