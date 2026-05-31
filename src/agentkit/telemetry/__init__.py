"""Telemetry subsystem -- events, emitters, storage, metrics, and projections.

Re-exports the public API for convenient access:

    from agentkit.telemetry import Event, EventType, MemoryEmitter
    from agentkit.telemetry import ProjectionAccessor, ProjectionKind
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
from agentkit.telemetry.storage import StateBackendEmitter

if TYPE_CHECKING:
    # Lazy zur Laufzeit (siehe __getattr__): ProjectionRecord referenziert
    # StoryMetricsRecord (story-closure). Eager-Import wuerde den Zyklus
    # telemetry <-> closure beim Package-Init reaktivieren.
    from agentkit.telemetry.projection_records import ProjectionRecord

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


def __getattr__(name: str) -> Any:
    """Lazy Laufzeit-Aufloesung von ``ProjectionRecord`` (PEP 562).

    ``ProjectionRecord`` ist ein reiner Typing-Alias ueber story-closure-eigene
    Record-Typen. Lazy-Aufloesung verhindert, dass ein Import von
    ``agentkit.telemetry`` (bzw. des Submoduls ``telemetry.events``) das
    story-closure-Package beim Init nachzieht (Anti-circular-import).

    Args:
        name: Angefragter Modul-Attributname.

    Returns:
        Den ``ProjectionRecord``-Union-Typ.

    Raises:
        AttributeError: Fuer alle anderen Namen.
    """
    if name == "ProjectionRecord":
        from agentkit.telemetry.projection_records import ProjectionRecord

        return ProjectionRecord
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
