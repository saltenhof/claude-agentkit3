"""Event emitters -- write events to storage backends.

Emitter is a Protocol (ARCH-06).  Concrete implementations:

- ``StateBackendEmitter``: persistent storage in the canonical state backend
- ``MemoryEmitter``: in-memory for testing
- ``NullEmitter``: /dev/null for when telemetry is disabled
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.telemetry.events import Event, EventType


@runtime_checkable
class EventEmitter(Protocol):
    """Contract for event emission (ARCH-06).

    Implementations MUST NOT raise for business errors (ARCH-20).
    Emission failures are logged but never block pipeline execution.
    """

    def emit(self, event: Event) -> None:
        """Emit a single event.

        Args:
            event: The immutable event to persist or process.
        """
        ...

    def query(
        self, _story_id: str, _event_type: EventType | None = None
    ) -> list[Event]:
        """Query events for a story, optionally filtered by type.

        Args:
            story_id: The story to query events for.
            event_type: Optional filter for a specific event type.

        Returns:
            List of matching events, ordered by timestamp ascending.
        """
        ...


class MemoryEmitter:
    """In-memory emitter for testing.  Not persistent.

    This is NOT a mock -- it is a first-class, production-quality
    implementation of the ``EventEmitter`` protocol that happens to
    store events in a plain list.
    """

    def __init__(self) -> None:
        self._events: list[Event] = []

    def emit(self, event: Event) -> None:
        """Append the event to the in-memory list.

        Args:
            event: The immutable event to store.
        """
        self._events.append(event)

    def query(
        self, story_id: str, event_type: EventType | None = None
    ) -> list[Event]:
        """Return events matching *story_id* and optional *event_type*.

        Args:
            story_id: The story to query events for.
            event_type: Optional filter for a specific event type.

        Returns:
            List of matching events.
        """
        results = [e for e in self._events if e.story_id == story_id]
        if event_type is not None:
            results = [e for e in results if e.event_type == event_type]
        return results

    @property
    def all_events(self) -> list[Event]:
        """Return a shallow copy of all stored events.

        Returns:
            List of all events regardless of story.
        """
        return list(self._events)

    def clear(self) -> None:
        """Remove all stored events."""
        self._events.clear()


class NullEmitter:
    """Emitter that discards all events.  For disabled telemetry."""

    def emit(self, event: Event) -> None:
        """Discard the event.

        Args:
            event: Ignored.
        """
        _ = event

    def query(
        self, story_id: str, event_type: EventType | None = None
    ) -> list[Event]:
        """Always return an empty list.

        Args:
            story_id: Ignored.
            event_type: Ignored.

        Returns:
            Empty list.
        """
        _ = story_id, event_type
        return []
