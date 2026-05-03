"""Telemetry contract records: canonical append-only runtime events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ("ExecutionEventRecord",)


@dataclass(frozen=True)
class ExecutionEventRecord:
    """Canonical append-only telemetry event for one runtime execution."""

    project_key: str
    story_id: str
    run_id: str
    event_id: str
    event_type: str
    occurred_at: datetime
    source_component: str
    severity: str
    phase: str | None = None
    flow_id: str | None = None
    node_id: str | None = None
    payload: dict[str, object] = field(default_factory=dict)
