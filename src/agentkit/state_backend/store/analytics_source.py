"""StateBackendAnalyticsSource — productive ``AnalyticsSourcePort`` (FK-62 §62.6.1).

Productive runtime read adapter for the KPI RefreshWorker (AG3-082). Implements the
consumer-owned ``AnalyticsSourcePort`` Protocol
(``agentkit.kpi_analytics.aggregation.source_port``) over the canonical runtime
read surfaces:

- the project-global ``execution_events`` stream (FK-68) — the watermark and the
  delta slice the worker classifies into dirty sets (FK-62 §62.3.4). The event
  stream is read through the ``state_backend.store`` facade; cross-project event
  reads are Postgres-canonical (FK-60 §60.3.2).
- ``telemetry.ProjectionAccessor`` (FK-69) — the story/corpus read-models
  (``story_metrics``, ``fc_incidents``) and the run-scoped reset purge
  (``purge_run``). FK-62 §62.6.1 hard rule: the KPI module reads the runtime
  schema ONLY through ``ProjectionAccessor`` and never holds a direct
  ``runtime.*`` connection — this adapter is the T-driver that satisfies that rule
  on behalf of the (DB-connection-free) aggregation worker.

This module is a T-driver (blood group T): it lives in ``state_backend.store`` and
is wired at the composition root. The aggregation worker imports ONLY the
``AnalyticsSourcePort`` Protocol, never this adapter (the AC6 ownership boundary,
enforced by ``tests/unit/kpi_analytics/aggregation/test_ownership_boundary.py``).

Reset purge (FK-62 §62.3.3 / FK-69 §69.10.1): ``purge_run_read_models`` delegates
to the REAL ``ProjectionAccessor.purge_run(project_key, story_id, run_id)`` — the
single AG3-081/FK-69 reset surface. There is no second purge abstraction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.kpi_analytics.aggregation.source_port import DeltaEvent
from agentkit.kpi_analytics.fact_store.guard_counter import week_start_for
from agentkit.kpi_analytics.fact_store.models import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStory,
)
from agentkit.telemetry.events import EventType
from agentkit.telemetry.projection_accessor import ProjectionFilter, ProjectionKind

if TYPE_CHECKING:
    from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.telemetry.contract.records import ExecutionEventRecord
    from agentkit.telemetry.projection_accessor import ProjectionAccessor

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

#: FK-62 §62.3.4: ``integrity_violation`` events feed the guard weeks.
_GUARD_EVENT_TYPE = EventType.INTEGRITY_VIOLATION.value

#: FK-62 §62.2.4: ``final_status`` value that marks an escalated (non-closed) story
#: for ``fact_pipeline_period.stories_escalated`` (the ``story_count_closed`` split).
_ESCALATED_STATUS = "ESCALATED"


def _month_start(instant: datetime) -> datetime:
    """Return the first-of-month UTC instant of ``instant`` (corpus grain)."""
    aware = instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)
    aware = aware.astimezone(UTC)
    return datetime(aware.year, aware.month, 1, tzinfo=UTC)


def _week_start_dt(week_start: str) -> datetime:
    """Parse a ``YYYY-MM-DD`` week-start key into a UTC instant."""
    return datetime.fromisoformat(week_start).replace(tzinfo=UTC)


class StateBackendAnalyticsSource:
    """Productive ``AnalyticsSourcePort`` over events + ``ProjectionAccessor``.

    Args:
        accessor: The FK-69 read surface (story/corpus read-models + the run-scoped
            ``purge_run`` reset). The KPI module reads ``runtime.*`` ONLY through
            this accessor (FK-62 §62.6.1).
        project_key: The project scope of this source (every read is scoped to it).
    """

    def __init__(self, accessor: ProjectionAccessor, *, project_key: str) -> None:
        self._accessor = accessor
        self._project_key = project_key

    # -- event stream (watermark + delta, FK-62 §62.3.2) --------------------

    def get_watermark(self, project_key: str) -> str | None:
        """Return the highest ``execution_events.event_id`` for ``project_key``.

        Reads the project-global event stream and returns the last (highest)
        ``event_id`` as the consistent upper bound of the sync run (FK-62 §62.3.2
        step 3). ``None`` means the project has no events yet.
        """
        events = self._load_project_events(project_key)
        if not events:
            return None
        return events[-1].event_id

    def read_delta_events(
        self,
        project_key: str,
        *,
        after_event_id: str | None,
        through_event_id: str,
    ) -> list[DeltaEvent]:
        """Return the events ``after_event_id < event_id <= through_event_id``.

        FK-62 §62.3.2 step 4. The event stream is ordered ``(occurred_at,
        event_id)``; the cursor compares on ``event_id`` (the monotonic key).
        """
        events = self._load_project_events(project_key)
        delta: list[DeltaEvent] = []
        for record in events:
            if after_event_id is not None and record.event_id <= after_event_id:
                continue
            if record.event_id > through_event_id:
                continue
            delta.append(_to_delta_event(record))
        return delta

    # -- story read-models (FK-62 §62.3.5) ----------------------------------

    def recompute_fact_story(
        self, project_key: str, story_id: str
    ) -> FactStory | None:
        """Recompute the ``fact_story`` row from ``story_metrics`` (FK-62 §62.3.5).

        Reads the story's ``story_metrics`` read-model through the accessor and maps
        the closure metrics onto the (AG3-038-pinned) ``FactStory`` columns. ``None``
        means the story has no materializable metrics yet (open story) — the worker
        then skips the upsert rather than writing a hollow row.
        """
        record = self._latest_story_metrics(project_key, story_id)
        if record is None:
            return None
        return _to_fact_story(record)

    def get_story_closed_at(
        self, project_key: str, story_id: str
    ) -> datetime | None:
        """Return the closure instant of ``story_id`` (FK-62 §62.3.4 hint week)."""
        record = self._latest_story_metrics(project_key, story_id)
        if record is None or not record.completed_at:
            return None
        return _parse_iso(record.completed_at)

    # -- period recomputes (FK-62 §62.3.5) ----------------------------------

    def recompute_fact_pool_period(
        self, project_key: str, pool_key: str, week_start: str
    ) -> FactPoolPeriod:
        """Recompute one pool-week from its ``llm_call`` / ``review_*`` events."""
        period_start = _week_start_dt(week_start)
        events = [
            e
            for e in self._load_project_events(project_key)
            if e.event_type in _POOL_EVENT_TYPES
            and _pool_of(e) == pool_key
            and week_start_for(e.occurred_at) == week_start
        ]
        period_end = max((e.occurred_at for e in events), default=period_start)
        return FactPoolPeriod(
            project_key=project_key,
            llm_role=pool_key,
            period_start=period_start,
            period_end=period_end,
            call_count=len(events),
            token_input_total=0,
            token_output_total=0,
            avg_latency_ms=None,
        )

    def recompute_fact_pipeline_period(
        self, project_key: str, week_start: str
    ) -> FactPipelinePeriod:
        """Recompute one pipeline-week from ``story_metrics`` (FK-62 §62.2.4).

        ``stories_completed`` / ``stories_escalated`` derive from the closed-week of
        each ``story_metrics`` row (its ``completed_at``), not from raw events — the
        finalised story read-model is the consistent source at closure (FK-62
        §62.3.4: story facts are finalised at closure). ``avg_qa_rounds`` is the
        mean over the week's completed stories.
        """
        period_start = _week_start_dt(week_start)
        in_week = [
            m
            for m in self._load_project_story_metrics(project_key)
            if m.completed_at
            and week_start_for(_parse_iso(m.completed_at)) == week_start
        ]
        period_end = max(
            (_parse_iso(m.completed_at) for m in in_week),
            default=period_start,
        )
        completed = [m for m in in_week if m.final_status != _ESCALATED_STATUS]
        escalated = [m for m in in_week if m.final_status == _ESCALATED_STATUS]
        avg_qa = (
            sum(m.qa_rounds for m in in_week) / len(in_week) if in_week else None
        )
        return FactPipelinePeriod(
            project_key=project_key,
            period_start=period_start,
            period_end=period_end,
            stories_completed=len(completed),
            stories_escalated=len(escalated),
            avg_qa_rounds=avg_qa,
        )

    def recompute_fact_corpus_period(
        self, project_key: str, month_start: str
    ) -> FactCorpusPeriod:
        """Recompute one corpus-month from ``fc_incidents`` (FK-62 §62.3.4 corpus)."""
        period_start = datetime.fromisoformat(month_start).replace(tzinfo=UTC)
        incidents = self._accessor.read_projection(
            ProjectionKind.FC_INCIDENTS,
            ProjectionFilter(project_key=project_key),
        )
        in_month = [
            inc
            for inc in incidents
            if _month_start(_incident_recorded_at(inc)) == period_start
        ]
        period_end = max(
            (_incident_recorded_at(inc) for inc in in_month),
            default=period_start,
        )
        return FactCorpusPeriod(
            project_key=project_key,
            period_start=period_start,
            period_end=period_end,
            incidents_recorded=len(in_month),
            patterns_promoted=0,
            checks_approved=0,
        )

    def recompute_fact_guard_period(
        self, project_key: str, guard_key: str, week_start: str
    ) -> FactGuardPeriod:
        """Recompute one guard-week from ``integrity_violation`` events.

        The scratchpad counter contribution (FK-62 §62.2.6) is folded in by the
        worker from the drained ``guard_invocation_counters`` rows; the runtime side
        here contributes only the event-derived violation count.
        """
        period_start = _week_start_dt(week_start)
        events = [
            e
            for e in self._load_project_events(project_key)
            if e.event_type == _GUARD_EVENT_TYPE
            and _guard_of(e) == guard_key
            and week_start_for(e.occurred_at) == week_start
        ]
        period_end = max((e.occurred_at for e in events), default=period_start)
        return FactGuardPeriod(
            project_key=project_key,
            guard_id=guard_key,
            period_start=period_start,
            period_end=period_end,
            invocation_count=len(events),
            violation_count=len(events),
        )

    # -- reset purge (FK-62 §62.3.3 / FK-69 §69.10.1) -----------------------

    def purge_run_read_models(
        self, project_key: str, story_id: str, run_id: str
    ) -> int:
        """Purge the run-bound FK-69 read models via the REAL ``purge_run``.

        Delegates to ``ProjectionAccessor.purge_run(project_key, story_id, run_id)``
        — the single AG3-081/FK-69 reset surface (FK-69 §69.10.1: run-scoped). The
        accessor's ``purge_run`` also drains the story's guard-counter scratchpad
        (AG3-081/FK-61 §61.4.3 Trigger 4), so the worker does NOT re-delete it.
        Returns the total number of run-bound FK-69 read-model rows removed.
        """
        result = self._accessor.purge_run(project_key, story_id, run_id)
        return sum(result.purged_rows.values())

    # -- internals ----------------------------------------------------------

    def _load_project_events(
        self, project_key: str
    ) -> list[ExecutionEventRecord]:
        from agentkit.state_backend.store.facade import (
            load_execution_events_for_project_global,
        )

        return load_execution_events_for_project_global(project_key)

    def _latest_story_metrics(
        self, project_key: str, story_id: str
    ) -> StoryMetricsRecord | None:
        from agentkit.closure.post_merge_finalization.records import (
            StoryMetricsRecord as _Record,
        )

        records = self._accessor.read_projection(
            ProjectionKind.STORY_METRICS,
            ProjectionFilter(project_key=project_key, story_id=story_id),
        )
        metrics = [r for r in records if isinstance(r, _Record)]
        if not metrics:
            return None
        # The story_metrics PK is (project_key, run_id); the current valid run is the
        # one with the latest completion. Pick the newest by completed_at.
        return max(metrics, key=lambda r: r.completed_at)

    def _load_project_story_metrics(
        self, project_key: str
    ) -> list[StoryMetricsRecord]:
        from agentkit.closure.post_merge_finalization.records import (
            StoryMetricsRecord as _Record,
        )

        records = self._accessor.read_projection(
            ProjectionKind.STORY_METRICS,
            ProjectionFilter(project_key=project_key),
        )
        return [r for r in records if isinstance(r, _Record)]


# ---------------------------------------------------------------------------
# mapping helpers
# ---------------------------------------------------------------------------


def _to_delta_event(record: ExecutionEventRecord) -> DeltaEvent:
    return DeltaEvent(
        event_id=record.event_id,
        story_id=record.story_id,
        event_type=record.event_type,
        occurred_at=record.occurred_at,
        pool_key=_pool_of(record),
        guard_key=_guard_of(record),
        payload=dict(record.payload),
    )


def _pool_of(record: ExecutionEventRecord) -> str | None:
    value = record.payload.get("pool_key") or record.payload.get("llm_role")
    return str(value) if value is not None else None


def _guard_of(record: ExecutionEventRecord) -> str | None:
    value = record.payload.get("guard_key") or record.payload.get("guard_id")
    return str(value) if value is not None else None


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _incident_recorded_at(incident: object) -> datetime:
    recorded = getattr(incident, "recorded_at", None)
    if isinstance(recorded, datetime):
        return recorded if recorded.tzinfo is not None else recorded.replace(tzinfo=UTC)
    if isinstance(recorded, str):
        return _parse_iso(recorded)
    raise TypeError(f"fc_incident has no usable recorded_at: {incident!r}")


def _to_fact_story(record: StoryMetricsRecord) -> FactStory:
    started = _parse_iso(record.completed_at)
    completed = _parse_iso(record.completed_at) if record.completed_at else None
    return FactStory(
        project_key=record.project_key,
        story_id=record.story_id,
        story_type=record.story_type,
        story_size=record.story_size,
        story_mode=record.mode,
        started_at=started,
        completed_at=completed,
        qa_rounds=record.qa_rounds,
        llm_call_count=len(record.llm_roles) or None,
        adversarial_findings=record.adversarial_findings,
        adversarial_tests_created=record.adversarial_tests_created,
        files_changed=record.files_changed,
        agentkit_version=record.agentkit_version or "unknown",
        agentkit_commit=record.agentkit_commit or "unknown",
    )


__all__ = ["StateBackendAnalyticsSource"]
