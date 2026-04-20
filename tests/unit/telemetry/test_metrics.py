"""Unit tests for agentkit.telemetry.metrics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.metrics import (
    PipelineMetrics,
    compute_phase_duration,
    compute_pipeline_metrics,
)


def _make_event(
    event_type: EventType,
    phase: str | None = None,
    ts: datetime | None = None,
    story_id: str = "AG3-001",
) -> Event:
    """Helper to construct events with minimal boilerplate."""
    return Event(
        story_id=story_id,
        event_type=event_type,
        phase=phase,
        timestamp=ts or datetime.now(UTC),
    )


class TestComputePipelineMetrics:
    """Tests for compute_pipeline_metrics."""

    def test_empty_events_returns_defaults(self) -> None:
        result = compute_pipeline_metrics([], "AG3-001")
        assert result.story_id == "AG3-001"
        assert result.total_duration_seconds is None
        assert result.phase_durations == {}
        assert result.qa_rounds == 0
        assert result.phases_executed == ()
        assert result.events_count == 0

    def test_phase_durations_from_started_completed_pairs(self) -> None:
        t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        t1 = t0 + timedelta(seconds=30)
        t2 = t0 + timedelta(seconds=60)
        t3 = t0 + timedelta(seconds=120)

        events = [
            _make_event(EventType.FLOW_START, phase="setup", ts=t0),
            _make_event(EventType.FLOW_END, phase="setup", ts=t1),
            _make_event(EventType.FLOW_START, phase="verify", ts=t2),
            _make_event(EventType.FLOW_END, phase="verify", ts=t3),
        ]
        result = compute_pipeline_metrics(events, "AG3-001")
        assert result.phase_durations["setup"] == 30.0
        assert result.phase_durations["verify"] == 60.0

    def test_total_duration_first_to_last_event(self) -> None:
        t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        t_end = t0 + timedelta(seconds=300)
        events = [
            _make_event(EventType.FLOW_START, phase="setup", ts=t0),
            _make_event(EventType.FLOW_END, phase="setup", ts=t_end),
        ]
        result = compute_pipeline_metrics(events, "AG3-001")
        assert result.total_duration_seconds == 300.0

    def test_qa_rounds_counts_verify_node_results(self) -> None:
        events = [
            _make_event(EventType.NODE_RESULT, phase="verify"),
            _make_event(EventType.NODE_RESULT, phase="verify"),
            _make_event(EventType.NODE_RESULT, phase="verify"),
        ]
        result = compute_pipeline_metrics(events, "AG3-001")
        assert result.qa_rounds == 3

    def test_phases_executed_from_node_results(self) -> None:
        t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        t1 = t0 + timedelta(seconds=10)
        t2 = t0 + timedelta(seconds=20)
        events = [
            _make_event(EventType.NODE_RESULT, phase="setup", ts=t0),
            _make_event(EventType.NODE_RESULT, phase="implementation", ts=t1),
            _make_event(EventType.NODE_RESULT, phase="verify", ts=t2),
        ]
        result = compute_pipeline_metrics(events, "AG3-001")
        assert result.phases_executed == ("setup", "implementation", "verify")

    def test_events_count(self) -> None:
        events = [
            _make_event(EventType.FLOW_START, phase="setup"),
            _make_event(EventType.FLOW_END, phase="setup"),
            _make_event(EventType.ERROR),
        ]
        result = compute_pipeline_metrics(events, "AG3-001")
        assert result.events_count == 3

    def test_phases_executed_deduplicates(self) -> None:
        """If a phase records multiple node results, it appears once."""
        t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        t1 = t0 + timedelta(seconds=60)
        events = [
            _make_event(EventType.NODE_RESULT, phase="verify", ts=t0),
            _make_event(EventType.NODE_RESULT, phase="verify", ts=t1),
        ]
        result = compute_pipeline_metrics(events, "AG3-001")
        assert result.phases_executed == ("verify",)


class TestComputePhaseDuration:
    """Tests for compute_phase_duration."""

    def test_start_and_end_returns_seconds(self) -> None:
        t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        t1 = t0 + timedelta(seconds=45)
        events = [
            _make_event(EventType.FLOW_START, phase="setup", ts=t0),
            _make_event(EventType.FLOW_END, phase="setup", ts=t1),
        ]
        result = compute_phase_duration(events, "setup")
        assert result == 45.0

    def test_missing_end_returns_none(self) -> None:
        events = [
            _make_event(EventType.FLOW_START, phase="setup"),
        ]
        result = compute_phase_duration(events, "setup")
        assert result is None

    def test_missing_start_returns_none(self) -> None:
        events = [
            _make_event(EventType.FLOW_END, phase="setup"),
        ]
        result = compute_phase_duration(events, "setup")
        assert result is None

    def test_empty_events_returns_none(self) -> None:
        result = compute_phase_duration([], "setup")
        assert result is None

    def test_wrong_phase_returns_none(self) -> None:
        t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        t1 = t0 + timedelta(seconds=10)
        events = [
            _make_event(EventType.FLOW_START, phase="setup", ts=t0),
            _make_event(EventType.FLOW_END, phase="setup", ts=t1),
        ]
        result = compute_phase_duration(events, "verify")
        assert result is None


class TestPipelineMetrics:
    """Tests for the PipelineMetrics dataclass."""

    def test_frozen(self) -> None:
        metrics = PipelineMetrics(story_id="AG3-001")
        # frozen=True should prevent attribute assignment
        try:
            metrics.story_id = "AG3-002"  # type: ignore[misc]
            raise AssertionError("Should have raised")  # noqa: B904
        except AttributeError:
            pass  # Expected

    def test_defaults(self) -> None:
        metrics = PipelineMetrics(story_id="AG3-001")
        assert metrics.total_duration_seconds is None
        assert metrics.phase_durations == {}
        assert metrics.qa_rounds == 0
        assert metrics.phases_executed == ()
        assert metrics.events_count == 0
