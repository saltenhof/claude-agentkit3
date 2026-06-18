"""RefreshWorker integration over the real FactStore + SQLite backend (AG3-082).

These exercise the FK-62 §62.3.2/§62.3.3 worker against a real on-disk SQLite
analytics schema (the Docker-free test-parallel backend): the real
``StateBackendFactRepository`` (incl. the new atomic write session, delete and
replace ports) and the real ``GuardCounterRepository`` for the scratchpad drain.
Only the runtime read side (``AnalyticsSourcePort``) is a test double — the
explicit §5 MOCKS-AUSNAHME boundary (mock at the projection/repository grenze).

Covered acceptance criteria:
- AC1  cursor read + advance (``last_event_id``).
- AC3  idempotency: a second sync with no new events is a no-op.
- AC4  atomicity: an error after ``replace_*_period`` and before the cursor
       update rolls the WHOLE transaction back (no fact change, cursor unchanged).
- AC7  ``purge_story_analytics``: fact_story deleted, FK-69 purge port invoked,
       periods recomputed, atomic rollback.
- AC8  guard-counter drain: counters folded into ``fact_guard_period`` AND the
       scratchpad rows deleted in the same transaction; reset removes them too.
- AC10 ``schema_version`` fail-closed (missing + mismatched), no worker-side seed.
- AC11 replace/delete/cursor ports used; replace empties a slice that recomputes
       to no row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.kpi_analytics.aggregation import (
    EXPECTED_SCHEMA_VERSION,
    AffectedPeriods,
    RefreshTrigger,
    RefreshWorker,
)
from agentkit.kpi_analytics.aggregation.models import SyncStatus
from agentkit.kpi_analytics.aggregation.source_port import DeltaEvent
from agentkit.kpi_analytics.errors import SchemaVersionError
from agentkit.kpi_analytics.fact_store import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStore,
    FactStory,
    PeriodFilter,
    SyncState,
)
from agentkit.state_backend.store.fact_repository import StateBackendFactRepository
from agentkit.state_backend.store.guard_counter_repository import (
    StateBackendGuardCounterRepository,
)
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PROJECT = "tenant-a"
_NOW = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
_WEEK = "2026-06-08"
_MONTH = "2026-06-01"
_WIDE = PeriodFilter(
    start=datetime(2020, 1, 1, tzinfo=UTC), end=datetime(2030, 1, 1, tzinfo=UTC)
)


@pytest.fixture(autouse=True)
def _pin_sqlite(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    from agentkit.state_backend.store import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


# ---------------------------------------------------------------------------
# Test double for the runtime read side (§5 MOCKS-AUSNAHME: projection boundary)
# ---------------------------------------------------------------------------


class _FakeSource:
    """In-memory ``AnalyticsSourcePort`` returning canned delta + recomputed rows.

    The reset purge consumes the REAL ``ProjectionAccessor.purge_run`` in production;
    here ``purge_run_read_models`` simulates that one reset surface — including the
    guard-counter scratchpad drain ``purge_run`` performs (AG3-081/FK-61 §61.4.3
    Trigger 4) — so the test exercises the same division of labour as production.
    """

    def __init__(
        self,
        *,
        watermark: str | None,
        delta: list[DeltaEvent] | None = None,
        counters: StateBackendGuardCounterRepository | None = None,
    ) -> None:
        self._watermark = watermark
        self._delta = delta or []
        self._counters = counters
        self.purge_calls: list[tuple[str, str, str]] = []
        self.closed_at: datetime | None = _NOW
        # Recompute stubs keyed by slice; default to deterministic rows.
        self.guard_invocations = 4
        self.guard_violations = 1

    def get_watermark(self, project_key: str) -> str | None:
        return self._watermark

    def get_story_closed_at(
        self, project_key: str, story_id: str
    ) -> datetime | None:
        return self.closed_at

    def read_delta_events(
        self,
        project_key: str,
        *,
        after_event_id: str | None,
        through_event_id: str,
    ) -> list[DeltaEvent]:
        return list(self._delta)

    def recompute_fact_story(
        self, project_key: str, story_id: str
    ) -> FactStory | None:
        return FactStory(
            project_key=project_key,
            story_id=story_id,
            story_type="implementation",
            story_size="L",
            opened_at=_NOW,
            closed_at=_NOW,
            qa_round_count=3,
            computed_at=_NOW,
        )

    def recompute_fact_pool_period(
        self, project_key: str, pool_key: str, week_start: str
    ) -> FactPoolPeriod:
        return FactPoolPeriod(
            project_key=project_key,
            pool_key=pool_key,
            period_start=datetime.fromisoformat(week_start).replace(tzinfo=UTC),
            call_count=2,
            response_time_p50_ms=300,
            computed_at=_NOW,
        )

    def recompute_fact_pipeline_period(
        self, project_key: str, week_start: str
    ) -> FactPipelinePeriod:
        return FactPipelinePeriod(
            project_key=project_key,
            period_start=datetime.fromisoformat(week_start).replace(tzinfo=UTC),
            story_count=1,
            story_count_closed=1,
            computed_at=_NOW,
        )

    def recompute_fact_corpus_period(
        self, project_key: str, month_start: str
    ) -> FactCorpusPeriod:
        return FactCorpusPeriod(
            project_key=project_key,
            period_start=datetime.fromisoformat(month_start).replace(tzinfo=UTC),
            new_incident_count=0,
            computed_at=_NOW,
        )

    def recompute_fact_guard_period(
        self, project_key: str, guard_key: str, week_start: str
    ) -> FactGuardPeriod:
        return FactGuardPeriod(
            project_key=project_key,
            guard_key=guard_key,
            period_start=datetime.fromisoformat(week_start).replace(tzinfo=UTC),
            invocation_count=self.guard_invocations,
            violation_count=self.guard_violations,
            computed_at=_NOW,
        )

    def purge_run_read_models(
        self, project_key: str, story_id: str, run_id: str
    ) -> int:
        # Simulate the REAL ProjectionAccessor.purge_run: it purges the run-bound
        # FK-69 read models AND drains the story's guard-counter scratchpad
        # (AG3-081/FK-61 §61.4.3 Trigger 4), in its own transaction.
        self.purge_calls.append((project_key, story_id, run_id))
        if self._counters is not None:
            self._counters.delete_counters_for_story(project_key, story_id)
        return 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store(tmp_path: Path) -> FactStore:
    return FactStore(StateBackendFactRepository(store_dir=tmp_path))


def _seed_schema_version(store: FactStore, version: int = EXPECTED_SCHEMA_VERSION) -> None:
    """Simulate the AG3-038 ``schema_version`` seed (story §2.2 — not worker-owned)."""
    store.upsert_sync_state(
        SyncState(
            project_key=_PROJECT,
            key="schema_version",
            value_int=version,
            updated_at=_NOW,
        )
    )


def _llm_event(event_id: str) -> DeltaEvent:
    return DeltaEvent(
        event_id=event_id,
        story_id="AG3-300",
        event_type=EventType.LLM_CALL.value,
        occurred_at=_NOW,
        pool_key="qa",
    )


# ---------------------------------------------------------------------------
# AC1 — cursor read + advance
# ---------------------------------------------------------------------------


def test_sync_reads_and_advances_cursor(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_schema_version(store)
    source = _FakeSource(watermark="evt-0005", delta=[_llm_event("evt-0003")])

    worker = RefreshWorker(store, source)
    result = worker.sync_analytics(
        RefreshTrigger.CLOSURE, _PROJECT, "AG3-300", now=_NOW
    )

    assert result.status is SyncStatus.SYNCED
    assert result.watermark == "evt-0005"
    assert result.events_processed == 1
    cursor = store.get_sync_state(_PROJECT, "last_event_id")
    assert cursor is not None
    assert cursor.value_text == "evt-0005"
    # The pool slice was written from the delta event.
    pools = store.list_fact_pool(_PROJECT, _WIDE)
    assert [p.pool_key for p in pools] == ["qa"]


# ---------------------------------------------------------------------------
# FIX 4 — the real worker path uses week_start(closed_at) for the hint pipeline week
# ---------------------------------------------------------------------------


def test_worker_uses_hint_closed_at_for_pipeline_week(tmp_path: Path) -> None:
    """The worker recomputes the hint story's pipeline slice for week(closed_at).

    Drives the real worker (real FactStore; source is the §5 MOCKS-AUSNAHME
    boundary): the hint story closed in a DIFFERENT ISO week than ``now``, so the
    worker must resolve ``closed_at`` through the source and recompute the
    pipeline slice for the CLOSED week — proving ``closed_at`` is threaded into
    ``derive_dirty_sets`` (review FIX 4), not the ``now`` fallback.
    """
    store = _store(tmp_path)
    _seed_schema_version(store)
    # now = 2026-06-11 (week 2026-06-08); hint closed 2026-05-28 (week 2026-05-25).
    closed_at = datetime(2026, 5, 28, 14, 0, tzinfo=UTC)
    closed_week = datetime.fromisoformat("2026-05-25").replace(tzinfo=UTC)
    now_week = datetime.fromisoformat(_WEEK).replace(tzinfo=UTC)
    # A delta event in a THIRD week (2026-06-01) so the now-week is NOT marked by an
    # event; only the hint's closed-week can put 2026-05-25 into the dirty set.
    third_week_event = DeltaEvent(
        event_id="evt-0003",
        story_id="AG3-300",
        event_type=EventType.AGENT_START.value,
        occurred_at=datetime(2026, 6, 3, 9, 0, tzinfo=UTC),  # week 2026-06-01
    )
    source = _FakeSource(watermark="evt-0005", delta=[third_week_event])
    source.closed_at = closed_at
    worker = RefreshWorker(store, source)

    worker.sync_analytics(RefreshTrigger.CLOSURE, _PROJECT, "AG3-999", now=_NOW)

    pipeline_weeks = {p.period_start for p in store.list_fact_pipeline(_PROJECT, _WIDE)}
    # The hint's CLOSED week is present (computed from closed_at, not now) ...
    assert closed_week in pipeline_weeks
    # ... and the now-week is NOT present (no event there; closed_at didn't fall back).
    assert now_week not in pipeline_weeks


# ---------------------------------------------------------------------------
# AC3 — idempotency: a second sync without new events is a no-op
# ---------------------------------------------------------------------------


def test_second_sync_without_new_events_is_no_op(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_schema_version(store)
    source = _FakeSource(watermark="evt-0005", delta=[_llm_event("evt-0003")])
    worker = RefreshWorker(store, source)

    first = worker.sync_analytics(RefreshTrigger.CLOSURE, _PROJECT, "AG3-300", now=_NOW)
    assert first.status is SyncStatus.SYNCED
    pools_before = store.list_fact_pool(_PROJECT, _WIDE)
    cursor_before = store.get_sync_state(_PROJECT, "last_event_id")

    # Watermark unchanged -> no-op.
    second = worker.sync_analytics(
        RefreshTrigger.DASHBOARD, _PROJECT, None, now=_NOW
    )

    assert second.status is SyncStatus.UP_TO_DATE
    assert second.events_processed == 0
    assert store.list_fact_pool(_PROJECT, _WIDE) == pools_before
    cursor_after = store.get_sync_state(_PROJECT, "last_event_id")
    assert cursor_after is not None and cursor_before is not None
    assert cursor_after.value_text == cursor_before.value_text == "evt-0005"


# ---------------------------------------------------------------------------
# AC4 — atomicity: error after replace_*_period, before cursor update
# ---------------------------------------------------------------------------


class _FailAfterReplaceSource(_FakeSource):
    """Raises during pipeline recompute — after pool replace, before cursor update."""

    def recompute_fact_pipeline_period(
        self, project_key: str, week_start: str
    ) -> FactPipelinePeriod:
        raise RuntimeError("injected failure after replace_*_period")


def test_failure_after_replace_rolls_back_whole_transaction(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_schema_version(store)
    # Pre-existing committed fact + cursor to prove nothing partial leaks.
    store.upsert_fact_pool(
        FactPoolPeriod(
            project_key=_PROJECT,
            pool_key="qa",
            period_start=datetime.fromisoformat(_WEEK).replace(tzinfo=UTC),
            call_count=99,
            computed_at=_NOW,
        )
    )
    store.upsert_sync_state(
        SyncState(
            project_key=_PROJECT,
            key="last_event_id",
            value_text="evt-0001",
            updated_at=_NOW,
        )
    )
    source = _FailAfterReplaceSource(watermark="evt-0005", delta=[_llm_event("evt-0003")])
    worker = RefreshWorker(store, source)

    with pytest.raises(RuntimeError, match="injected failure"):
        worker.sync_analytics(RefreshTrigger.CLOSURE, _PROJECT, "AG3-300", now=_NOW)

    # No partial commit: the pool slice keeps its old committed value (the replace
    # rolled back) and the cursor is unchanged.
    pools = store.list_fact_pool(_PROJECT, _WIDE)
    assert [p.call_count for p in pools] == [99]
    cursor = store.get_sync_state(_PROJECT, "last_event_id")
    assert cursor is not None and cursor.value_text == "evt-0001"


# ---------------------------------------------------------------------------
# AC8 — guard-counter drain (transferred + scratchpad deleted, same txn)
# ---------------------------------------------------------------------------


def test_guard_counter_drain_transfers_and_deletes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_schema_version(store)
    counters = StateBackendGuardCounterRepository(tmp_path)
    # Two invocations, one blocked, in the hint story's scratchpad.
    counters.upsert_invocation(
        project_key=_PROJECT,
        story_id="AG3-300",
        guard_key="orchestrator_guard",
        week_start=_WEEK,
        blocked=True,
        updated_at=_NOW,
    )
    counters.upsert_invocation(
        project_key=_PROJECT,
        story_id="AG3-300",
        guard_key="orchestrator_guard",
        week_start=_WEEK,
        blocked=False,
        updated_at=_NOW,
    )
    assert len(counters.read_counters_for_story(_PROJECT, "AG3-300")) == 1

    source = _FakeSource(watermark="evt-0005", delta=[_llm_event("evt-0003")])
    source.guard_invocations = 10  # runtime/event contribution
    source.guard_violations = 2
    worker = RefreshWorker(store, source)
    worker.sync_analytics(RefreshTrigger.CLOSURE, _PROJECT, "AG3-300", now=_NOW)

    guards = store.list_fact_guards(_PROJECT, _WIDE)
    assert len(guards) == 1
    # 10 runtime + 2 drained invocations; 2 runtime + 1 drained block.
    assert guards[0].invocation_count == 12
    assert guards[0].violation_count == 3
    # The processed scratchpad rows are gone (no growing residual table).
    assert counters.read_counters_for_story(_PROJECT, "AG3-300") == []


# ---------------------------------------------------------------------------
# AC10 — schema_version fail-closed (no worker-side seed)
# ---------------------------------------------------------------------------


def test_missing_schema_version_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)  # no seed at all
    source = _FakeSource(watermark="evt-0005", delta=[_llm_event("evt-0003")])
    worker = RefreshWorker(store, source)

    with pytest.raises(SchemaVersionError) as exc:
        worker.sync_analytics(RefreshTrigger.CLOSURE, _PROJECT, "AG3-300", now=_NOW)

    assert exc.value.found is None
    # Worker did NOT seed the version (seed owner is AG3-038, story §2.2).
    assert store.get_sync_state(_PROJECT, "schema_version") is None


def test_mismatched_schema_version_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_schema_version(store, version=EXPECTED_SCHEMA_VERSION + 1)
    source = _FakeSource(watermark="evt-0005", delta=[_llm_event("evt-0003")])
    worker = RefreshWorker(store, source)

    with pytest.raises(SchemaVersionError) as exc:
        worker.sync_analytics(RefreshTrigger.CLOSURE, _PROJECT, "AG3-300", now=_NOW)

    assert exc.value.found == EXPECTED_SCHEMA_VERSION + 1
    # Worker did NOT overwrite/seed the version.
    state = store.get_sync_state(_PROJECT, "schema_version")
    assert state is not None and state.value_int == EXPECTED_SCHEMA_VERSION + 1


# ---------------------------------------------------------------------------
# AC7 / AC11 — purge_story_analytics: delete + port + recompute + rollback
# ---------------------------------------------------------------------------


def test_purge_deletes_fact_story_calls_port_and_recomputes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    # A committed fact_story row + a guard slice + scratchpad for the reset story.
    store.upsert_fact_story(
        FactStory(
            project_key=_PROJECT,
            story_id="AG3-300",
            story_type="implementation",
            story_size="L",
            opened_at=_NOW,
            qa_round_count=1,
            computed_at=_NOW,
        )
    )
    store.upsert_fact_guard(
        FactGuardPeriod(
            project_key=_PROJECT,
            guard_key="orchestrator_guard",
            period_start=datetime.fromisoformat(_WEEK).replace(tzinfo=UTC),
            invocation_count=99,
            violation_count=9,
            computed_at=_NOW,
        )
    )
    counters = StateBackendGuardCounterRepository(tmp_path)
    counters.upsert_invocation(
        project_key=_PROJECT,
        story_id="AG3-300",
        guard_key="orchestrator_guard",
        week_start=_WEEK,
        blocked=False,
        updated_at=_NOW,
    )
    source = _FakeSource(watermark=None, counters=counters)
    source.guard_invocations = 3
    source.guard_violations = 0
    worker = RefreshWorker(store, source)

    worker.purge_story_analytics(
        _PROJECT,
        "AG3-300",
        "run-7",
        AffectedPeriods(
            guard_weeks=frozenset({(_PROJECT, "orchestrator_guard", _WEEK)})
        ),
    )

    # fact_story row gone (FK-62 §62.2.8).
    assert store.list_fact_stories(_PROJECT) == []
    # REAL run-scoped FK-69 purge surface invoked with run_id (AG3-081 owns it).
    assert source.purge_calls == [(_PROJECT, "AG3-300", "run-7")]
    # Guard slice recomputed from remaining valid sources (no orphan 99 value).
    guards = store.list_fact_guards(_PROJECT, _WIDE)
    assert len(guards) == 1
    assert guards[0].invocation_count == 3
    # Scratchpad of the reset story removed by the run-scoped purge (purge_run),
    # NOT by a second worker-side delete.
    assert counters.read_counters_for_story(_PROJECT, "AG3-300") == []


class _PurgeFailSource(_FakeSource):
    def recompute_fact_guard_period(
        self, project_key: str, guard_key: str, week_start: str
    ) -> FactGuardPeriod:
        raise RuntimeError("injected purge recompute failure")


def test_purge_rolls_back_analytics_writes_on_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_fact_story(
        FactStory(
            project_key=_PROJECT,
            story_id="AG3-300",
            story_type="implementation",
            story_size="S",
            opened_at=_NOW,
            qa_round_count=1,
            computed_at=_NOW,
        )
    )
    source = _PurgeFailSource(watermark=None)
    worker = RefreshWorker(store, source)

    with pytest.raises(RuntimeError, match="injected purge recompute"):
        worker.purge_story_analytics(
            _PROJECT,
            "AG3-300",
            "run-9",
            AffectedPeriods(
                guard_weeks=frozenset({(_PROJECT, "orchestrator_guard", _WEEK)})
            ),
        )

    # The fact_story delete rolled back with the failed recompute (no partial purge).
    assert [s.story_id for s in store.list_fact_stories(_PROJECT)] == ["AG3-300"]
    # The REAL run-scoped purge ran first (its own txn); the analytics writes then
    # rolled back as a unit — no half-applied analytics reset (FK-62 §62.3.3/§62.3.7).
    assert source.purge_calls == [(_PROJECT, "AG3-300", "run-9")]


# ---------------------------------------------------------------------------
# AC11 — replace empties a slice that recomputes to no row
# ---------------------------------------------------------------------------


def test_replace_empties_slice_with_no_recomputed_row(tmp_path: Path) -> None:
    """A purge affecting a pool-week with no recompute row deletes the slice."""
    store = _store(tmp_path)
    store.upsert_fact_pool(
        FactPoolPeriod(
            project_key=_PROJECT,
            pool_key="qa",
            period_start=datetime.fromisoformat(_WEEK).replace(tzinfo=UTC),
            call_count=42,
            computed_at=_NOW,
        )
    )

    # Drive a single delete+insert via the session directly: keys present, rows empty.
    week_dt = datetime.fromisoformat(_WEEK).replace(tzinfo=UTC)
    repo = StateBackendFactRepository(store_dir=tmp_path)
    with repo.begin_write_session() as session:
        session.replace_pool_period([(_PROJECT, "qa", week_dt)], [])

    assert store.list_fact_pool(_PROJECT, _WIDE) == []
