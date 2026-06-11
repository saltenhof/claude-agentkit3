"""RefreshWorker — the idempotent analytics aggregation worker (FK-62 §62.3).

This is the recompute half of the FK-62 §62.3 Refresh-Worker (the AG3-081 hot-path
/ purge-port half is consumed, not rebuilt). ``sync_analytics`` is an idempotent
repair worker (FK-62 §62.3.2): read the cursor/watermark, read the delta, derive
the five typed dirty sets (FK-62 §62.3.4), recompute each touched slice COMPLETELY
(FK-62 §62.3.5) and write everything plus the advanced cursor in ONE atomic
transaction (FK-62 §62.3.7 — no partial commit, the next run re-processes the same
delta idempotently). ``purge_story_analytics`` is the reset-purge baton AG3-071
calls (FK-62 §62.3.3): it consumes the REAL AG3-081/FK-69 run-scoped purge surface
(``ProjectionAccessor.purge_run(project_key, story_id, run_id)``) and then, in ONE
atomic analytics-write transaction, deletes the ``fact_story`` row and recomputes
the affected period rollups from the remaining valid sources.

Reset atomicity (FK-62 §62.3.3 / §62.3.7): the FK-69 read-model purge and the
analytics write are owned by two different write owners (telemetry vs. the
analytics ``FactStore``); FK-62 §62.3.7 forbids a cross-DB commit. The ordering
guarantee is therefore: (1) the run-scoped FK-69 purge runs first inside its own
transaction — if it fails, NO analytics write has happened (the reset aborts
clean); (2) the analytics writes then run inside ONE FactStore transaction — if
either side fails the analytics writes roll back as a unit. No half-applied
analytics reset can survive either failure.

Ownership boundary (FK-62 §62.6.1/§62.6.2): the worker reads ONLY through the
injected ``AnalyticsSourcePort`` (backed by ``ProjectionAccessor`` /
``Telemetry.read_projection`` at the composition root) and writes ONLY through the
``FactStore`` (incl. its atomic write session). It holds NO ``runtime.*`` DB
connection and imports NO ``state_backend.store`` write facade.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.kpi_analytics.aggregation.dirty_sets import derive_dirty_sets
from agentkit.kpi_analytics.aggregation.models import (
    AffectedPeriods,
    RefreshTrigger,
    SyncResult,
    SyncStatus,
)
from agentkit.kpi_analytics.errors import SchemaVersionError
from agentkit.kpi_analytics.fact_store.models import FactGuardPeriod, SyncState

if TYPE_CHECKING:
    from agentkit.kpi_analytics.aggregation.dirty_sets import DirtySets
    from agentkit.kpi_analytics.aggregation.source_port import AnalyticsSourcePort
    from agentkit.kpi_analytics.fact_store.models import GuardInvocationCounter
    from agentkit.kpi_analytics.fact_store.repository import FactWriteSession
    from agentkit.kpi_analytics.fact_store.store import FactStore

#: FK-62 §62.4.3 / story AC10: the schema version the worker expects. The current
#: FK-62 schema is the first version, so the initial expected value is ``1``. The
#: worker only READS and compares it; the seed/writer is AG3-038 (story §2.2).
EXPECTED_SCHEMA_VERSION = 1

#: FK-62 §62.2.7 ``sync_state`` keys consumed by the worker.
_CURSOR_KEY = "last_event_id"
_LAST_SYNCED_KEY = "last_synced_at"
_SCHEMA_VERSION_KEY = "schema_version"


class RefreshWorker:
    """Idempotent analytics aggregation worker (FK-62 §62.3.2/§62.3.3).

    Args:
        fact_store: The analytics write driver (FK-62 §62.6.2) — the ONLY write
            path into the fact tables (incl. its atomic write session).
        source: The runtime read port (FK-62 §62.6.1) — the ONLY runtime read
            path; backed by ``ProjectionAccessor`` at the composition root.
    """

    def __init__(self, fact_store: FactStore, source: AnalyticsSourcePort) -> None:
        self._fact_store = fact_store
        self._source = source

    # ------------------------------------------------------------------
    # sync_analytics (FK-62 §62.3.2)
    # ------------------------------------------------------------------

    def sync_analytics(
        self,
        trigger: RefreshTrigger,
        project_key: str,
        hint_story_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> SyncResult:
        """Aggregate the runtime read-models into the fact tables (FK-62 §62.3.2).

        Idempotent repair worker: reads the cursor/watermark, derives the dirty
        sets from the delta + ``hint_story_id``, recomputes the touched slices and
        writes them with the advanced cursor in one atomic transaction. A second
        call with no new events is a no-op (``watermark <= last_event_id`` ->
        ``UP_TO_DATE``; the cursor is left unchanged).

        Args:
            trigger: The typed refresh trigger (FK-62 §62.3.1).
            project_key: The project scope.
            hint_story_id: The Closure hint story (FK-62 §62.3.4).
            now: Override for the current instant (the corpus-month / hint-week
                anchor). Defaults to ``datetime.now(UTC)``.

        Returns:
            ``SyncResult`` (``UP_TO_DATE`` no-op or ``SYNCED`` with the processed
            count and advanced watermark).

        Raises:
            SchemaVersionError: Fail-closed on a missing/mismatched
                ``schema_version`` (FK-62 §62.4.3).
        """
        instant = now or datetime.now(UTC)
        self._assert_schema_version(project_key)

        last_event_id = self._read_cursor(project_key)
        watermark = self._source.get_watermark(project_key)

        # FK-62 §62.3.2 step 3 (idempotent no-op): a watermark that has not advanced
        # past the persisted cursor recomputes nothing and leaves the cursor
        # untouched. The corpus full-recompute (FK-62 §62.3.4) runs only once there
        # is a real delta to process — mirroring the FK-62 §62.3.2 reference, which
        # returns ``up_to_date`` before deriving any dirty set.
        if watermark is None or (
            last_event_id is not None and watermark <= last_event_id
        ):
            return SyncResult(status=SyncStatus.UP_TO_DATE, trigger=trigger)

        delta_events = self._source.read_delta_events(
            project_key,
            after_event_id=last_event_id,
            through_event_id=watermark,
        )
        # FK-62 §62.3.4: the hint story's pipeline week is week_start(closed_at),
        # NOT week_start(now). Resolve the real closure instant through the read
        # port (the worker holds no runtime DB connection); ``None`` falls back to
        # the sync instant inside ``derive_dirty_sets``.
        hint_closed_at = (
            self._source.get_story_closed_at(project_key, hint_story_id)
            if hint_story_id
            else None
        )
        dirty = derive_dirty_sets(
            project_key,
            delta_events,
            hint_story_id=hint_story_id,
            hint_closed_at=hint_closed_at,
            now=instant,
        )

        with self._fact_store.begin_write_session() as session:
            self._recompute_into(session, project_key, dirty, drain_story_id=hint_story_id)
            session.update_sync_cursor(
                SyncState(
                    project_key=project_key,
                    key=_CURSOR_KEY,
                    value_text=watermark,
                    updated_at=instant,
                )
            )
            session.update_sync_cursor(
                SyncState(
                    project_key=project_key,
                    key=_LAST_SYNCED_KEY,
                    value_text=instant.isoformat(),
                    updated_at=instant,
                )
            )

        return SyncResult(
            status=SyncStatus.SYNCED,
            trigger=trigger,
            events_processed=len(delta_events),
            watermark=watermark,
        )

    # ------------------------------------------------------------------
    # purge_story_analytics (FK-62 §62.3.3)
    # ------------------------------------------------------------------

    def purge_story_analytics(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        affected_periods: AffectedPeriods,
    ) -> None:
        """Reset-purge one story's analytics derivations (FK-62 §62.3.3 / §62.2.8).

        Consumes the REAL AG3-081/FK-69 run-scoped purge surface
        (``ProjectionAccessor.purge_run(project_key, story_id, run_id)``) through
        ``AnalyticsSourcePort.purge_run_read_models`` (story §2.2 — invoked, not
        re-implemented; there is no second purge abstraction). That call removes the
        run-bound FK-69 read models AND drains the story's guard-counter scratchpad
        (AG3-081/FK-61 §61.4.3 Trigger 4 already does this inside ``purge_run``), so
        the worker does NOT re-delete the scratchpad here — that would be a second
        operative truth over a row the telemetry BC already owns.

        Then, in ONE atomic analytics-write transaction (rollback on any failure),
        it deletes the ``fact_story`` row and recomputes the affected period rollups
        from the remaining valid sources. After the purge no orphaned aggregate
        contribution survives (FK-62 §62.2.8: fully reset runs disappear from the
        fact tables).

        Atomicity / ordering (FK-62 §62.3.3 / §62.3.7 — two write owners, no
        cross-DB commit): the FK-69 purge runs FIRST inside its own transaction. If
        it raises, NO analytics write has happened and the reset aborts clean. The
        analytics writes then run inside ONE FactStore transaction; if either side
        raises, the analytics writes roll back as a unit. Neither failure can leave
        a half-applied analytics reset.

        Args:
            project_key: The project scope.
            story_id: The reset story whose derivations are purged.
            run_id: The reset run whose FK-69 read models are purged (FK-69
                §69.10.1: the purge is run-scoped, not merely story-scoped).
            affected_periods: The period rollups to recompute (FK-62 §62.3.3).
        """
        # Step 1 — REAL AG3-081/FK-69 run-scoped purge (story §2.2). Runs in its
        # OWN transaction OUTSIDE the analytics session: the FK-69 read models (and
        # the guard-counter scratchpad it also drains) are owned by the telemetry
        # BC, and FK-62 §62.3.7 forbids a cross-DB commit. Ordering guarantee: if
        # this raises, no analytics write has happened yet.
        self._source.purge_run_read_models(project_key, story_id, run_id)

        # Step 2 — analytics writes in ONE atomic FactStore transaction (rollback on
        # any failure): delete the fact_story row and recompute the affected period
        # rollups. The guard-counter scratchpad is NOT touched here (step 1 already
        # drained it via purge_run).
        with self._fact_store.begin_write_session() as session:
            session.delete_fact_story(project_key, story_id)

            self._replace_guard_periods(
                session, sorted(affected_periods.guard_weeks), drained=[]
            )
            self._replace_pool_periods(session, sorted(affected_periods.pool_weeks))
            self._replace_pipeline_periods(
                session, sorted(affected_periods.pipeline_weeks)
            )
            self._replace_corpus_periods(
                session, sorted(affected_periods.corpus_months)
            )

    # ------------------------------------------------------------------
    # internal recompute orchestration
    # ------------------------------------------------------------------

    def _recompute_into(
        self,
        session: FactWriteSession,
        project_key: str,
        dirty: DirtySets,
        *,
        drain_story_id: str | None,
    ) -> None:
        """Recompute and write every dirty slice through the open session."""
        # fact_story (FK-62 §62.3.5): recompute each dirty story completely.
        for _pk, story_id in sorted(dirty.dirty_story_ids):
            fact = self._source.recompute_fact_story(project_key, story_id)
            if fact is not None:
                session.upsert_fact_story(fact)

        # Guard counters drain (FK-62 §62.2.6): drain the closing story's
        # scratchpad rows IN-SESSION, fold them into the dirty guard weeks, then
        # delete them — the fact_guard_period write and the scratchpad delete
        # commit atomically.
        drained: list[GuardInvocationCounter] = []
        if drain_story_id is not None:
            drained = session.read_guard_counters_for_story(
                project_key, drain_story_id
            )
            if drained:
                session.delete_guard_counters_for_story(project_key, drain_story_id)

        guard_weeks = set(dirty.dirty_guard_weeks)
        for counter in drained:
            guard_weeks.add((project_key, counter.guard_key, counter.week_start))

        self._replace_guard_periods(session, sorted(guard_weeks), drained=drained)
        self._replace_pool_periods(session, sorted(dirty.dirty_pool_weeks))
        self._replace_pipeline_periods(session, sorted(dirty.dirty_pipeline_weeks))
        self._replace_corpus_periods(session, sorted(dirty.dirty_corpus_months))

    def _replace_guard_periods(
        self,
        session: FactWriteSession,
        slices: list[tuple[str, str, str]],
        *,
        drained: list[GuardInvocationCounter],
    ) -> None:
        if not slices:
            return
        drained_by_slice: dict[tuple[str, str, str], GuardInvocationCounter] = {
            (c.project_key, c.guard_key, c.week_start): c for c in drained
        }
        rows: list[FactGuardPeriod] = []
        keys: list[tuple[str, str, datetime]] = []
        for slice_key in slices:
            project_key, guard_key, week_start = slice_key
            base = self._source.recompute_fact_guard_period(
                project_key, guard_key, week_start
            )
            counter = drained_by_slice.get(slice_key)
            if counter is not None:
                base = base.model_copy(
                    update={
                        "invocation_count": base.invocation_count
                        + counter.invocations,
                        "violation_count": base.violation_count + counter.blocks,
                    }
                )
            rows.append(base)
            keys.append((project_key, guard_key, base.period_start))
        session.replace_guard_period(keys, rows)

    def _replace_pool_periods(
        self, session: FactWriteSession, slices: list[tuple[str, str, str]]
    ) -> None:
        if not slices:
            return
        rows = [
            self._source.recompute_fact_pool_period(pk, pool_key, week_start)
            for pk, pool_key, week_start in slices
        ]
        keys = [(r.project_key, r.llm_role, r.period_start) for r in rows]
        session.replace_pool_period(keys, rows)

    def _replace_pipeline_periods(
        self, session: FactWriteSession, slices: list[tuple[str, str]]
    ) -> None:
        if not slices:
            return
        rows = [
            self._source.recompute_fact_pipeline_period(pk, week_start)
            for pk, week_start in slices
        ]
        keys = [(r.project_key, r.period_start) for r in rows]
        session.replace_pipeline_period(keys, rows)

    def _replace_corpus_periods(
        self, session: FactWriteSession, slices: list[tuple[str, str]]
    ) -> None:
        if not slices:
            return
        rows = [
            self._source.recompute_fact_corpus_period(pk, month_start)
            for pk, month_start in slices
        ]
        keys = [(r.project_key, r.period_start) for r in rows]
        session.replace_corpus_period(keys, rows)

    # ------------------------------------------------------------------
    # cursor / schema-version (FK-62 §62.2.7 / §62.4.3)
    # ------------------------------------------------------------------

    def _read_cursor(self, project_key: str) -> str | None:
        state = self._fact_store.get_sync_state(project_key, _CURSOR_KEY)
        return state.value_text if state is not None else None

    def _assert_schema_version(self, project_key: str) -> None:
        """Fail-closed on a missing/mismatched ``schema_version`` (FK-62 §62.4.3).

        The worker READS the version only; it never seeds/writes it (seed owner is
        AG3-038, story §2.2). A missing seed or a divergent value raises
        ``SchemaVersionError`` so the worker stops rather than aggregating against
        an unknown schema.
        """
        state = self._fact_store.get_sync_state(project_key, _SCHEMA_VERSION_KEY)
        found = state.value_int if state is not None else None
        if found != EXPECTED_SCHEMA_VERSION:
            raise SchemaVersionError(expected=EXPECTED_SCHEMA_VERSION, found=found)


__all__ = ["EXPECTED_SCHEMA_VERSION", "RefreshWorker"]
