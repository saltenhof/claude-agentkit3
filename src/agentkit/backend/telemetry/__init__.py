"""Telemetry subsystem -- events, emitters, storage, metrics, and projections.

Re-exports the public API for convenient access:

    from agentkit.backend.telemetry import Event, EventType, MemoryEmitter
    from agentkit.backend.telemetry import ProjectionAccessor, ProjectionKind
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.backend.telemetry.emitters import (
    EventEmitter,
    MemoryEmitter,
    NullEmitter,
)
from agentkit.backend.telemetry.errors import ProjectionRecordTypeMismatchError
from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.metrics import PipelineMetrics, compute_pipeline_metrics
from agentkit.backend.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
    PurgeResult,
)
from agentkit.backend.telemetry.storage import StateBackendEmitter

if TYPE_CHECKING:
    # Lazy at runtime (see __getattr__): ProjectionRecord references
    # StoryMetricsRecord (story-closure). An eager import would reactivate the
    # telemetry <-> closure cycle during package init.
    from agentkit.backend.telemetry.projection_records import ProjectionRecord

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
    """Lazy runtime resolution of ``ProjectionRecord`` (PEP 562).

    ``ProjectionRecord`` is a pure typing alias over story-closure-owned
    record types. Lazy resolution prevents an import of
    ``agentkit.backend.telemetry`` (or the submodule ``telemetry.events``) from
    pulling in the story-closure package at init time (anti-circular-import).

    Args:
        name: Requested module attribute name.

    Returns:
        The ``ProjectionRecord`` union type.

    Raises:
        AttributeError: For all other names.
    """
    if name == "ProjectionRecord":
        from agentkit.backend.telemetry.projection_records import ProjectionRecord

        return ProjectionRecord
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
