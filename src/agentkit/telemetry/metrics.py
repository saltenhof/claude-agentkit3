"""Metrics computation from telemetry events.

Pure functions -- no side effects (ARCH-31).  Input: events.  Output:
metrics.  Every metric is derived deterministically from the event stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentkit.telemetry.events import Event, EventType


@dataclass(frozen=True)
class PipelineMetrics:
    """Aggregated metrics for a story's pipeline run.

    All fields are derived from the event stream -- no external state.

    Args:
        story_id: Identifier of the story these metrics belong to.
        total_duration_seconds: Wall-clock seconds from first to last event.
        phase_durations: Mapping of phase name to duration in seconds.
        qa_rounds: Number of QA decision rounds observed.
        phases_executed: Tuple of phase names that were started.
        events_count: Total number of events in the input stream.
    """

    story_id: str
    total_duration_seconds: float | None = None
    phase_durations: dict[str, float] = field(default_factory=dict)
    qa_rounds: int = 0
    phases_executed: tuple[str, ...] = ()
    events_count: int = 0


def compute_pipeline_metrics(
    events: list[Event], story_id: str
) -> PipelineMetrics:
    """Compute pipeline metrics from a list of events.

    Pure function -- derives everything from the event stream.

    Args:
        events: All events belonging to a pipeline run.
        story_id: The story identifier for the resulting metrics.

    Returns:
        A ``PipelineMetrics`` instance with all computable fields populated.
    """
    if not events:
        return PipelineMetrics(story_id=story_id)

    # Total duration: first event to last event
    sorted_events = sorted(events, key=lambda e: e.timestamp)
    first_ts = sorted_events[0].timestamp
    last_ts = sorted_events[-1].timestamp
    total_seconds = (last_ts - first_ts).total_seconds()
    total_duration = total_seconds if total_seconds > 0 else None

    # Phase durations from PHASE_STARTED -> PHASE_COMPLETED pairs
    phase_durations: dict[str, float] = {}
    phase_starts: dict[str, Event] = {}
    for evt in sorted_events:
        if evt.event_type == EventType.PHASE_STARTED and evt.phase is not None:
            phase_starts[evt.phase] = evt
        elif (
            evt.event_type == EventType.PHASE_COMPLETED
            and evt.phase is not None
            and evt.phase in phase_starts
        ):
            duration = compute_phase_duration(
                [phase_starts[evt.phase], evt], evt.phase
            )
            if duration is not None:
                phase_durations[evt.phase] = duration

    # QA rounds: count QA_DECISION events
    qa_rounds = sum(
        1 for e in events if e.event_type == EventType.QA_DECISION
    )

    # Phases executed: unique phase names from PHASE_STARTED events
    phases_executed = tuple(
        dict.fromkeys(
            e.phase
            for e in sorted_events
            if e.event_type == EventType.PHASE_STARTED and e.phase is not None
        )
    )

    return PipelineMetrics(
        story_id=story_id,
        total_duration_seconds=total_duration,
        phase_durations=phase_durations,
        qa_rounds=qa_rounds,
        phases_executed=phases_executed,
        events_count=len(events),
    )


def compute_phase_duration(events: list[Event], phase: str) -> float | None:
    """Compute duration of a single phase in seconds.

    Looks for a ``PHASE_STARTED`` and ``PHASE_COMPLETED`` event pair
    matching the given *phase* name.

    Args:
        events: Events to search (should be from a single story/run).
        phase: The phase name to compute duration for.

    Returns:
        Duration in seconds, or ``None`` if start or end event is missing.
    """
    start_event: Event | None = None
    end_event: Event | None = None

    for evt in events:
        if (
            evt.event_type == EventType.PHASE_STARTED
            and evt.phase == phase
            and start_event is None
        ):
            start_event = evt
        elif (
            evt.event_type == EventType.PHASE_COMPLETED
            and evt.phase == phase
            and end_event is None
        ):
            end_event = evt

    if start_event is None or end_event is None:
        return None

    return (end_event.timestamp - start_event.timestamp).total_seconds()
