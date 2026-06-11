"""Dirty-set derivation matrix (FK-62 §62.3.4, story AC2).

Five targeted asserts — one per dirty set — that the derivation builds each set
from the FK-62 §62.3.4 source class: ``dirty_story_ids`` / ``dirty_guard_weeks`` /
``dirty_pool_weeks`` / ``dirty_pipeline_weeks`` from the delta events + the closure
hint, and ``dirty_corpus_months`` always as ``(project_key, current_month)``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.kpi_analytics.aggregation import derive_dirty_sets
from agentkit.kpi_analytics.aggregation.dirty_sets import month_start_for
from agentkit.kpi_analytics.aggregation.source_port import DeltaEvent
from agentkit.telemetry.events import EventType

_PROJECT = "tenant-a"
# 2026-06-11 is a Thursday; ISO week starts Monday 2026-06-08.
_NOW = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
_WEEK = "2026-06-08"


def _event(
    event_id: str,
    *,
    story_id: str = "AG3-300",
    event_type: str = EventType.AGENT_START.value,
    pool_key: str | None = None,
    guard_key: str | None = None,
    occurred_at: datetime = _NOW,
) -> DeltaEvent:
    return DeltaEvent(
        event_id=event_id,
        story_id=story_id,
        event_type=event_type,
        occurred_at=occurred_at,
        pool_key=pool_key,
        guard_key=guard_key,
    )


def test_dirty_story_ids_from_delta_events_and_hint() -> None:
    dirty = derive_dirty_sets(
        _PROJECT,
        [_event("1", story_id="AG3-300"), _event("2", story_id="AG3-301")],
        hint_story_id="AG3-999",
        hint_closed_at=_NOW,
        now=_NOW,
    )
    assert dirty.dirty_story_ids == frozenset(
        {
            (_PROJECT, "AG3-300"),
            (_PROJECT, "AG3-301"),
            (_PROJECT, "AG3-999"),
        }
    )


def test_dirty_guard_weeks_from_integrity_violation_events() -> None:
    dirty = derive_dirty_sets(
        _PROJECT,
        [
            _event(
                "1",
                event_type=EventType.INTEGRITY_VIOLATION.value,
                guard_key="orchestrator_guard",
            ),
            # A non-guard event contributes nothing to dirty_guard_weeks.
            _event("2", event_type=EventType.AGENT_START.value),
        ],
        hint_story_id=None,
        hint_closed_at=None,
        now=_NOW,
    )
    assert dirty.dirty_guard_weeks == frozenset(
        {(_PROJECT, "orchestrator_guard", _WEEK)}
    )


def test_dirty_pool_weeks_from_llm_and_review_events() -> None:
    dirty = derive_dirty_sets(
        _PROJECT,
        [
            _event("1", event_type=EventType.LLM_CALL.value, pool_key="qa"),
            _event("2", event_type=EventType.REVIEW_RESPONSE.value, pool_key="review"),
        ],
        hint_story_id=None,
        hint_closed_at=None,
        now=_NOW,
    )
    assert dirty.dirty_pool_weeks == frozenset(
        {(_PROJECT, "qa", _WEEK), (_PROJECT, "review", _WEEK)}
    )


def test_dirty_pipeline_weeks_from_all_events_plus_hint_closed_week() -> None:
    last_week = datetime(2026, 6, 4, 9, 0, tzinfo=UTC)  # week of 2026-06-01
    dirty = derive_dirty_sets(
        _PROJECT,
        [_event("1", occurred_at=last_week)],
        hint_story_id="AG3-999",
        hint_closed_at=_NOW,  # closed in week 2026-06-08
        now=_NOW,
    )
    assert dirty.dirty_pipeline_weeks == frozenset(
        {(_PROJECT, "2026-06-01"), (_PROJECT, _WEEK)}
    )


def test_dirty_corpus_months_is_always_current_month() -> None:
    dirty = derive_dirty_sets(
        _PROJECT,
        [],  # no events at all
        hint_story_id=None,
        hint_closed_at=None,
        now=_NOW,
    )
    assert dirty.dirty_corpus_months == frozenset(
        {(_PROJECT, month_start_for(_NOW))}
    )
    assert month_start_for(_NOW) == "2026-06-01"


def test_month_start_for_treats_naive_instant_as_utc() -> None:
    naive = datetime(2026, 6, 17, 3, 0)  # no tzinfo
    assert month_start_for(naive) == "2026-06-01"


def test_pipeline_week_falls_back_to_now_when_hint_closed_at_missing() -> None:
    """A hint with no closed-at instant uses ``now`` for the hint pipeline week."""
    dirty = derive_dirty_sets(
        _PROJECT,
        [],
        hint_story_id="AG3-999",
        hint_closed_at=None,
        now=_NOW,
    )
    assert dirty.dirty_pipeline_weeks == frozenset({(_PROJECT, _WEEK)})
