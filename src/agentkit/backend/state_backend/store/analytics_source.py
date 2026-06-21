"""StateBackendAnalyticsSource — productive ``AnalyticsSourcePort`` (FK-62 §62.6.1).

Productive runtime read adapter for the KPI RefreshWorker (AG3-082). Implements the
consumer-owned ``AnalyticsSourcePort`` Protocol
(``agentkit.backend.kpi_analytics.aggregation.source_port``) over the canonical runtime
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

from agentkit.backend.kpi_analytics.aggregation.source_port import DeltaEvent
from agentkit.backend.kpi_analytics.fact_store.guard_counter import week_start_for
from agentkit.backend.kpi_analytics.fact_store.models import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStory,
)
from agentkit.backend.telemetry.events import EventType
from agentkit.backend.telemetry.projection_accessor import ProjectionFilter, ProjectionKind

if TYPE_CHECKING:
    from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
    from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor

#: FK-62 §62.3.4: ``llm_call`` / ``review_*`` events feed the pool weeks.
#:
#: AG3-117: the pool-identity payload key is NOT uniform across these event types.
#: Each producer emits its pool identity under a DIFFERENT canonical wire key, so a
#: single ``payload[...]`` lookup silently misses most of them. The authoritative
#: per-type key lives in :data:`_POOL_PAYLOAD_KEY_BY_TYPE` (the SINGLE SOURCE OF
#: TRUTH for the read-boundary mapping); this set is derived from it so the set and
#: the key-map cannot drift (a guard test asserts the two stay in lock-step).
_POOL_PAYLOAD_KEY_BY_TYPE: dict[EventType, str | None] = {
    # ``llm_call``: producers (``structured_evaluator.py:806``,
    # ``adversarial_orchestrator/runtime/sparring.py:178``) emit BOTH ``pool`` and
    # ``role``; the telemetry contract (``telemetry_contract.py:239-241``) makes
    # ``pool`` AUTHORITATIVE (a self-reported ``role`` alone is NOT accepted).
    EventType.LLM_CALL: "pool",
    # ``llm_call_complete``: the review-completion sink
    # (``composition_root.py:1464``) emits ONLY ``role`` (the reviewer pool); pinned
    # mandatory by ``_event_payload_contracts.py:51``.
    EventType.LLM_CALL_COMPLETE: "role",
    # ``review_request`` / ``review_response`` / ``review_compliant``: the review
    # sentinel hook (``review_sentinel_hook.py:80``) emits the reviewer pool under
    # ``reviewer_role`` (NOT ``role`` / ``pool``); ``review_guard.py:166`` reads the
    # same key back.
    EventType.REVIEW_REQUEST: "reviewer_role",
    EventType.REVIEW_RESPONSE: "reviewer_role",
    EventType.REVIEW_COMPLIANT: "reviewer_role",
    # ``review_guard_intervention``: emitted by ``review_guard.py:104-110`` as a
    # cross-pool coverage fact carrying ``missing_roles`` / ``required_roles``
    # (LISTS) — it has NO single scalar pool dimension, so it intentionally maps to
    # ``None`` (it dirties the pipeline week, never a specific pool week). Explicit
    # ``None`` (a deliberate decision, NOT a default-guess) so the fail-closed guard
    # distinguishes it from an unmapped/forgotten event type.
    EventType.REVIEW_GUARD_INTERVENTION: None,
    # ``review_divergence``: emitted by ``divergence_hook.py:73-80`` as a
    # reviewer-PAIR fact (``reviewer_a`` / ``reviewer_b``) — a divergence between two
    # pools, with no single pool dimension, so it likewise maps to explicit ``None``.
    EventType.REVIEW_DIVERGENCE: None,
}

#: Wire-value-keyed view of :data:`_POOL_PAYLOAD_KEY_BY_TYPE` (event filtering is on
#: ``ExecutionEventRecord.event_type``, a wire string).
_POOL_EVENT_TYPES: frozenset[str] = frozenset(
    et.value for et in _POOL_PAYLOAD_KEY_BY_TYPE
)

#: FK-62 §62.3.4: ``integrity_violation`` events feed the guard weeks. AG3-117:
#: same event-type-aware mapping as the pool side. ``integrity_violation`` carries
#: the emitting guard under ``guard`` (``_event_payload_contracts.py:64``; producers
#: ``prompt_integrity_guard.py``, ``skill_usage_check.py``,
#: ``web_call_budget_guard.py`` — all ``payload={"guard": ...}``).
_GUARD_PAYLOAD_KEY_BY_TYPE: dict[EventType, str | None] = {
    EventType.INTEGRITY_VIOLATION: "guard",
}

#: Wire-value-keyed view of :data:`_GUARD_PAYLOAD_KEY_BY_TYPE`.
_GUARD_EVENT_TYPES: frozenset[str] = frozenset(
    et.value for et in _GUARD_PAYLOAD_KEY_BY_TYPE
)

#: FK-62 §62.2.4: ``final_status`` value that marks an escalated (non-closed) story.
#: The pipeline week splits ``story_count`` (all stories in the week) from
#: ``story_count_closed`` (the non-escalated subset, FK-62 §62.2.4).
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
        return FactPoolPeriod(
            project_key=project_key,
            pool_key=pool_key,
            period_start=period_start,
            call_count=len(events),
            computed_at=datetime.now(UTC),
        )

    def recompute_fact_pipeline_period(
        self, project_key: str, week_start: str
    ) -> FactPipelinePeriod:
        """Recompute one pipeline-week from ``story_metrics`` (FK-62 §62.2.4).

        ``story_count`` / ``story_count_closed`` derive from the closed-week of
        each ``story_metrics`` row (its ``completed_at``), not from raw events — the
        finalised story read-model is the consistent source at closure (FK-62
        §62.3.4: story facts are finalised at closure). ``qa_round_avg`` is the
        mean over the week's stories. The remaining FK-62 §62.2.4 columns keep
        their typed defaults; their fill-logic is AG3-082 territory.
        """
        period_start = _week_start_dt(week_start)
        in_week = [
            m
            for m in self._load_project_story_metrics(project_key)
            if m.completed_at
            and week_start_for(_parse_iso(m.completed_at)) == week_start
        ]
        closed = [m for m in in_week if m.final_status != _ESCALATED_STATUS]
        avg_qa = (
            sum(m.qa_rounds for m in in_week) / len(in_week) if in_week else None
        )
        return FactPipelinePeriod(
            project_key=project_key,
            period_start=period_start,
            story_count=len(in_week),
            story_count_closed=len(closed),
            qa_round_avg=avg_qa,
            computed_at=datetime.now(UTC),
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
        return FactCorpusPeriod(
            project_key=project_key,
            period_start=period_start,
            new_incident_count=len(in_month),
            computed_at=datetime.now(UTC),
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
            if e.event_type in _GUARD_EVENT_TYPES
            and _guard_of(e) == guard_key
            and week_start_for(e.occurred_at) == week_start
        ]
        return FactGuardPeriod(
            project_key=project_key,
            guard_key=guard_key,
            period_start=period_start,
            invocation_count=len(events),
            violation_count=len(events),
            computed_at=datetime.now(UTC),
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
        from agentkit.backend.state_backend.store.facade import (
            load_execution_events_for_project_global,
        )

        return load_execution_events_for_project_global(project_key)

    def _latest_story_metrics(
        self, project_key: str, story_id: str
    ) -> StoryMetricsRecord | None:
        from agentkit.backend.closure.post_merge_finalization.records import (
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
        from agentkit.backend.closure.post_merge_finalization.records import (
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


def _resolve_payload_key(
    event_type: str, key_map: dict[EventType, str | None]
) -> str | None:
    """Resolve the authoritative pool/guard payload key for ``event_type``.

    AG3-117 (R3): the pool/guard identity is carried under DIFFERENT canonical wire
    keys per event type (``llm_call`` -> ``pool``, ``llm_call_complete`` -> ``role``,
    ``review_*`` -> ``reviewer_role``, ``integrity_violation`` -> ``guard``), so a
    single payload lookup silently misses most of them. This function selects the
    correct key per event type from the SINGLE-SOURCE-OF-TRUTH ``key_map``.

    FAIL-CLOSED (project rule): an event type that is a MEMBER of the rollup set but
    has no entry in ``key_map`` (e.g. a future addition to ``_POOL_EVENT_TYPES`` /
    ``_GUARD_EVENT_TYPES`` whose key the author forgot to pin) raises ``KeyError``
    rather than silently defaulting to ``None`` — a silent ``None`` would re-create
    exactly the AG3-117 data bug (the slice would capture nothing without anyone
    noticing). Callers (``_pool_of`` / ``_guard_of``) only invoke this for events
    already filtered to the rollup set, so the lookup is total over that domain.

    Args:
        event_type: The wire ``event_type`` string of the record.
        key_map: The per-``EventType`` authoritative payload-key map (pool or guard).

    Returns:
        The payload key to read, or ``None`` for an event type that is in the rollup
        set but carries no single scalar pool/guard dimension (explicitly mapped to
        ``None``, e.g. ``review_divergence`` / ``review_guard_intervention``).

    Raises:
        KeyError: The event type has no entry in ``key_map`` (fail-closed: an
            unmapped member of the rollup set is a contract gap, not a no-op).
    """
    return key_map[EventType(event_type)]


def _pool_of(record: ExecutionEventRecord) -> str | None:
    # Select the CANONICAL pool-identity wire key for THIS event type
    # (event-type-aware, AG3-117 R3) and translate it to the ``pool_key`` FK-62
    # §62.2 fact dimension. Records outside ``_POOL_EVENT_TYPES`` carry no pool
    # dimension; an event type in the set but absent from the key-map fails closed
    # (see ``_resolve_payload_key``). NO producer emits the bare fact-column name
    # ``pool_key`` on the payload — that lookup is the bug this story fixes.
    if record.event_type not in _POOL_EVENT_TYPES:
        return None
    payload_key = _resolve_payload_key(record.event_type, _POOL_PAYLOAD_KEY_BY_TYPE)
    if payload_key is None:
        return None
    value = record.payload.get(payload_key)
    return str(value) if value is not None else None


def _guard_of(record: ExecutionEventRecord) -> str | None:
    # Select the CANONICAL guard-identity wire key for THIS event type
    # (event-type-aware, AG3-117 R3) and translate it to the ``guard_key`` FK-62
    # §62.2 fact dimension. Records outside ``_GUARD_EVENT_TYPES`` carry no guard
    # dimension; an event type in the set but absent from the key-map fails closed.
    # NO producer emits the bare fact-column name ``guard_key`` on the payload.
    if record.event_type not in _GUARD_EVENT_TYPES:
        return None
    payload_key = _resolve_payload_key(record.event_type, _GUARD_PAYLOAD_KEY_BY_TYPE)
    if payload_key is None:
        return None
    value = record.payload.get(payload_key)
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
    opened = _parse_iso(record.completed_at)
    closed = _parse_iso(record.completed_at) if record.completed_at else None
    return FactStory(
        project_key=record.project_key,
        story_id=record.story_id,
        story_type=record.story_type,
        story_size=record.story_size,
        pipeline_mode=record.mode,
        opened_at=opened,
        closed_at=closed,
        processing_time_ms=round(record.processing_time_min * 60_000),
        qa_round_count=record.qa_rounds,
        final_status=record.final_status,
        llm_call_count=len(record.llm_roles),
        adversarial_findings_count=record.adversarial_findings or 0,
        adversarial_tests_created=record.adversarial_tests_created or 0,
        files_changed=record.files_changed or 0,
        increment_count=record.increments,
        computed_at=datetime.now(UTC),
    )


__all__ = ["StateBackendAnalyticsSource"]
