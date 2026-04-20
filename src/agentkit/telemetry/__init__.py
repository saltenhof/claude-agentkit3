"""Telemetry subsystem -- events, emitters, storage, and metrics.

Re-exports the public API for convenient access:

    from agentkit.telemetry import Event, EventType, MemoryEmitter
"""

from __future__ import annotations

from agentkit.telemetry.emitters import (
    EventEmitter,
    MemoryEmitter,
    NullEmitter,
)
from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.metrics import PipelineMetrics, compute_pipeline_metrics
from agentkit.telemetry.storage import StateBackendEmitter

__all__ = [
    "Event",
    "EventEmitter",
    "EventType",
    "MemoryEmitter",
    "NullEmitter",
    "PipelineMetrics",
    "StateBackendEmitter",
    "compute_pipeline_metrics",
]
