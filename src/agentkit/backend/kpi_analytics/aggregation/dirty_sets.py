"""Dirty-set derivation for the RefreshWorker (FK-62 §62.3.4).

The five dirty sets are the typed slices the worker recomputes (FK-62 §62.3.5).
They are derived from two sources (FK-62 §62.3.4): the runtime delta events AND
the closure hint (``hint_story_id``). Each set is a typed ``frozenset[tuple[...]]``
(story §5 TYPISIERT STATT STRINGS), keyed by the natural grain of its fact table:

- ``dirty_story_ids``     : ``(project_key, story_id)``
- ``dirty_guard_weeks``   : ``(project_key, guard_key, week_start)``
- ``dirty_pool_weeks``    : ``(project_key, pool_key, week_start)``
- ``dirty_pipeline_weeks``: ``(project_key, week_start)``
- ``dirty_corpus_months`` : ``(project_key, current_month)``  (always, FK-62 §62.3.4)

The event-type classification references the canonical ``telemetry.events.EventType``
values (SINGLE SOURCE OF TRUTH — no re-invented string literals). This module is a
pure A-bloodtype derivation (no I/O).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agentkit.backend.kpi_analytics.fact_store.guard_counter import week_start_for
from agentkit.backend.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from agentkit.backend.kpi_analytics.aggregation.source_port import DeltaEvent

#: FK-62 §62.3.4: ``integrity_violation`` events feed the guard weeks.
_GUARD_EVENT_TYPES: frozenset[str] = frozenset({EventType.INTEGRITY_VIOLATION.value})

#: FK-62 §62.3.4: ``llm_call`` / ``review_*`` events feed the pool weeks.
_POOL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        EventType.LLM_CALL.value,
        EventType.LLM_CALL_COMPLETE.value,
        EventType.REVIEW_REQUEST.value,
        EventType.REVIEW_RESPONSE.value,
        EventType.REVIEW_COMPLIANT.value,
        EventType.REVIEW_GUARD_INTERVENTION.value,
        EventType.REVIEW_DIVERGENCE.value,
    }
)


def month_start_for(instant: datetime) -> str:
    """Return the ``YYYY-MM-01`` first-of-month key of ``instant`` (UTC-normalised).

    The corpus grain is monthly (FK-62 §62.2.5). Mirrors ``week_start_for``'s
    timezone normalisation: a naive instant is treated as UTC.
    """
    from datetime import UTC

    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    utc_instant = instant.astimezone(UTC)
    return utc_instant.date().replace(day=1).isoformat()


class DirtySets(BaseModel):
    """The five typed dirty sets the worker recomputes (FK-62 §62.3.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dirty_story_ids: frozenset[tuple[str, str]] = frozenset()
    dirty_guard_weeks: frozenset[tuple[str, str, str]] = frozenset()
    dirty_pool_weeks: frozenset[tuple[str, str, str]] = frozenset()
    dirty_pipeline_weeks: frozenset[tuple[str, str]] = frozenset()
    dirty_corpus_months: frozenset[tuple[str, str]] = frozenset()


def derive_dirty_sets(
    project_key: str,
    delta_events: Iterable[DeltaEvent],
    *,
    hint_story_id: str | None,
    hint_closed_at: datetime | None,
    now: datetime,
) -> DirtySets:
    """Derive the five FK-62 §62.3.4 dirty sets from delta events + the closure hint.

    Args:
        project_key: The project scope key (leading key of every dirty tuple).
        delta_events: The runtime delta events of this sync (FK-62 §62.3.2 step 4).
        hint_story_id: The Closure hint story (FK-62 §62.3.4) — added to
            ``dirty_story_ids`` and its closed-week to ``dirty_pipeline_weeks``.
        hint_closed_at: The hint story's ``closed_at`` instant, used for the hint
            pipeline week (FK-62 §62.3.4: "week_start(closed_at) der hint_story").
            Falls back to ``now`` when the closed-at instant is unknown.
        now: The current instant — fixes the corpus month (FK-62 §62.3.4 corpus
            special case: always ``(project_key, current_month)``).

    Returns:
        The typed ``DirtySets``. ``dirty_corpus_months`` always contains exactly
        ``(project_key, month_start_for(now))`` (corpus has no event cursor).
    """
    story_ids: set[tuple[str, str]] = set()
    guard_weeks: set[tuple[str, str, str]] = set()
    pool_weeks: set[tuple[str, str, str]] = set()
    pipeline_weeks: set[tuple[str, str]] = set()

    for event in delta_events:
        week = week_start_for(event.occurred_at)
        # Every delta event marks its pipeline week dirty (FK-62 §62.3.4).
        pipeline_weeks.add((project_key, week))
        if event.story_id:
            story_ids.add((project_key, event.story_id))
        if event.event_type in _GUARD_EVENT_TYPES and event.guard_key:
            guard_weeks.add((project_key, event.guard_key, week))
        if event.event_type in _POOL_EVENT_TYPES and event.pool_key:
            pool_weeks.add((project_key, event.pool_key, week))

    # Closure hint (FK-62 §62.3.4): the just-closed story + its closed-week.
    if hint_story_id:
        story_ids.add((project_key, hint_story_id))
        hint_week = week_start_for(hint_closed_at or now)
        pipeline_weeks.add((project_key, hint_week))

    # Corpus special case (FK-62 §62.3.4): always the current month, no cursor.
    corpus_months: set[tuple[str, str]] = {(project_key, month_start_for(now))}

    return DirtySets(
        dirty_story_ids=frozenset(story_ids),
        dirty_guard_weeks=frozenset(guard_weeks),
        dirty_pool_weeks=frozenset(pool_weeks),
        dirty_pipeline_weeks=frozenset(pipeline_weeks),
        dirty_corpus_months=frozenset(corpus_months),
    )


__all__ = ["DirtySets", "derive_dirty_sets", "month_start_for"]
