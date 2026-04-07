"""Telemetry event model -- immutable facts about what happened.

Events are facts, not commands (ARCH-41). All frozen (ARCH-29).
Domain terms explicitly modeled via EventType enum (ARCH-14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class EventType(StrEnum):
    """Catalog of all telemetry event types (ARCH-14).

    Each value is a domain-specific fact type that describes what happened
    in the pipeline.  Never used as a command -- events record history.
    """

    # Pipeline lifecycle
    PHASE_STARTED = "phase_started"
    PHASE_COMPLETED = "phase_completed"
    PHASE_FAILED = "phase_failed"
    PHASE_YIELDED = "phase_yielded"
    PHASE_RESUMED = "phase_resumed"

    # QA
    QA_LAYER_STARTED = "qa_layer_started"
    QA_LAYER_COMPLETED = "qa_layer_completed"
    QA_DECISION = "qa_decision"

    # Worker
    WORKER_SPAWNED = "worker_spawned"
    WORKER_COMPLETED = "worker_completed"

    # Guard / Governance
    GUARD_EVALUATED = "guard_evaluated"
    INTEGRITY_CHECK = "integrity_check"

    # GitHub
    ISSUE_CLOSED = "issue_closed"
    ISSUE_CREATED = "issue_created"

    # General
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Event:
    """An immutable telemetry event (ARCH-29).

    Events are facts -- they record what happened, not what should happen
    (ARCH-41).  The ``payload`` dict carries event-specific data without
    requiring subclasses for every event type.

    Args:
        story_id: Identifier of the story this event belongs to.
        event_type: Categorisation from the ``EventType`` enum.
        timestamp: UTC instant when the event occurred (auto-populated).
        phase: Pipeline phase name, if applicable.
        payload: Arbitrary structured data describing the event detail.
        run_id: Optional identifier linking events to a single pipeline run.
    """

    story_id: str
    event_type: EventType
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    phase: str | None = None
    payload: dict[str, object] = field(default_factory=dict)
    run_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize the event to a plain dictionary for storage.

        Returns:
            Dictionary with all fields serialised to JSON-safe types.
        """
        return {
            "story_id": self.story_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "phase": self.phase,
            "payload": self.payload,
            "run_id": self.run_id,
        }
