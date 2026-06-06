"""Unit tests for FactStore (AG3-038 AC3, AC8, §7).

Two layers:

* a hand-rolled in-memory ``_FakeRepository`` proves the FactStore is a thin,
  faithful delegate (every method routes to the repository, return values pass
  through unchanged) and that a repository error PROPAGATES (FAIL-CLOSED, §7 — no
  empty-result fallback in the FactStore);
* a real ``StateBackendFactRepository`` on ``tmp_path`` (SQLite, unit conftest
  forces sqlite) proves the read/write round-trip against the actual table.

The Postgres backend of the same logic is exercised by the contract test
(``tests/contract/state_backend/test_analytics_schema.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.kpi_analytics.fact_store import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactRepository,
    FactStore,
    FactStory,
    PeriodFilter,
    SyncState,
)
from agentkit.state_backend.store.fact_repository import StateBackendFactRepository

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
_LATER = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
_PERIOD = PeriodFilter(start=_NOW, end=datetime(2026, 7, 1, tzinfo=UTC))


def _story(story_id: str = "AG3-001", *, qa: int = 3) -> FactStory:
    return FactStory(
        project_key="p1",
        story_id=story_id,
        story_type="implementation",
        story_size="L",
        story_mode="standard",
        started_at=_NOW,
        completed_at=_LATER,
        qa_rounds=qa,
        compaction_count=1,
        llm_call_count=12,
        feedback_converged=True,
        files_changed=4,
        agentkit_version="3.19.0",
        agentkit_commit="deadbeef",
    )


class _FakeRepository:
    """In-memory FactRepository double recording the last call per method."""

    def __init__(self, *, raise_on_read: bool = False) -> None:
        self._raise = raise_on_read
        self.stories: list[FactStory] = []
        self.last_sync: SyncState | None = None
        self.upserts: list[str] = []

    def list_fact_stories(
        self, project_key: str, period: PeriodFilter | None = None
    ) -> list[FactStory]:
        if self._raise:
            raise RuntimeError("missing table: fact_story")
        return [s for s in self.stories if s.project_key == project_key]

    def list_fact_guards(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactGuardPeriod]:
        return []

    def list_fact_pool(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactPoolPeriod]:
        return []

    def list_fact_pipeline(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactPipelinePeriod]:
        return []

    def list_fact_corpus(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactCorpusPeriod]:
        return []

    def get_sync_state(self, project_key: str, key: str) -> SyncState | None:
        return self.last_sync

    def upsert_fact_story(self, fact: FactStory) -> None:
        self.upserts.append("story")
        self.stories.append(fact)

    def upsert_fact_guard(self, fact: FactGuardPeriod) -> None:
        self.upserts.append("guard")

    def upsert_fact_pool(self, fact: FactPoolPeriod) -> None:
        self.upserts.append("pool")

    def upsert_fact_pipeline(self, fact: FactPipelinePeriod) -> None:
        self.upserts.append("pipeline")

    def upsert_fact_corpus(self, fact: FactCorpusPeriod) -> None:
        self.upserts.append("corpus")

    def upsert_sync_state(self, state: SyncState) -> None:
        self.last_sync = state


def test_fake_repository_satisfies_protocol() -> None:
    assert isinstance(_FakeRepository(), FactRepository)


def test_store_delegates_upsert_and_read() -> None:
    repo = _FakeRepository()
    store = FactStore(repo)
    store.upsert_fact_story(_story())
    assert repo.upserts == ["story"]
    assert store.list_fact_stories("p1") == [_story()]
    assert store.list_fact_stories("other") == []


def test_store_propagates_read_error_fail_closed() -> None:
    """§7: a repository error (e.g. missing table) is NOT swallowed into []."""
    store = FactStore(_FakeRepository(raise_on_read=True))
    with pytest.raises(RuntimeError, match="missing table"):
        store.list_fact_stories("p1")


def test_store_sync_state_roundtrip_via_fake() -> None:
    repo = _FakeRepository()
    store = FactStore(repo)
    assert store.get_sync_state("p1", "last_event_id") is None
    state = SyncState(project_key="p1", key="last_event_id", updated_at=_NOW)
    store.upsert_sync_state(state)
    assert store.get_sync_state("p1", "last_event_id") == state


# --- real SQLite backend roundtrip -----------------------------------------


def test_real_store_upsert_then_list(tmp_path: Path) -> None:
    store = FactStore(StateBackendFactRepository(tmp_path))
    store.upsert_fact_story(_story("AG3-001", qa=3))
    store.upsert_fact_story(_story("AG3-002", qa=5))
    rows = store.list_fact_stories("p1")
    assert [r.story_id for r in rows] == ["AG3-001", "AG3-002"]
    assert rows[0].feedback_converged is True
    assert rows[1].qa_rounds == 5


def test_real_store_upsert_is_idempotent(tmp_path: Path) -> None:
    """AC5/§7: re-upsert on the same PK updates in place, no duplicate row."""
    store = FactStore(StateBackendFactRepository(tmp_path))
    store.upsert_fact_story(_story("AG3-001", qa=3))
    store.upsert_fact_story(_story("AG3-001", qa=9))  # same PK, new value
    rows = store.list_fact_stories("p1")
    assert len(rows) == 1
    assert rows[0].qa_rounds == 9


def test_real_store_list_stories_period_filter(tmp_path: Path) -> None:
    store = FactStore(StateBackendFactRepository(tmp_path))
    store.upsert_fact_story(_story("AG3-001"))
    in_window = store.list_fact_stories("p1", _PERIOD)
    assert [r.story_id for r in in_window] == ["AG3-001"]
    empty_window = store.list_fact_stories(
        "p1",
        PeriodFilter(
            start=datetime(2020, 1, 1, tzinfo=UTC),
            end=datetime(2020, 2, 1, tzinfo=UTC),
        ),
    )
    assert empty_window == []


def test_real_store_all_five_fact_tables_roundtrip(tmp_path: Path) -> None:
    store = FactStore(StateBackendFactRepository(tmp_path))
    store.upsert_fact_story(_story("AG3-001"))
    store.upsert_fact_guard(
        FactGuardPeriod(
            project_key="p1",
            guard_id="g1",
            period_start=_NOW,
            period_end=_LATER,
            invocation_count=7,
            violation_count=1,
        )
    )
    store.upsert_fact_pool(
        FactPoolPeriod(
            project_key="p1",
            llm_role="worker",
            period_start=_NOW,
            period_end=_LATER,
            call_count=3,
            token_input_total=100,
            token_output_total=40,
            avg_latency_ms=250,
        )
    )
    store.upsert_fact_pipeline(
        FactPipelinePeriod(
            project_key="p1",
            period_start=_NOW,
            period_end=_LATER,
            stories_completed=2,
            stories_escalated=0,
            avg_qa_rounds=2.5,
        )
    )
    store.upsert_fact_corpus(
        FactCorpusPeriod(
            project_key="p1",
            period_start=_NOW,
            period_end=_LATER,
            incidents_recorded=1,
            patterns_promoted=0,
            checks_approved=0,
        )
    )
    assert len(store.list_fact_stories("p1")) == 1
    assert store.list_fact_guards("p1", _PERIOD)[0].invocation_count == 7
    assert store.list_fact_pool("p1", _PERIOD)[0].avg_latency_ms == 250
    assert store.list_fact_pipeline("p1", _PERIOD)[0].avg_qa_rounds == 2.5
    assert store.list_fact_corpus("p1", _PERIOD)[0].incidents_recorded == 1


def test_real_store_sync_state_roundtrip(tmp_path: Path) -> None:
    store = FactStore(StateBackendFactRepository(tmp_path))
    assert store.get_sync_state("p1", "last_event_id") is None
    state = SyncState(
        project_key="p1",
        key="last_event_id",
        value_text="11111111-1111-1111-1111-111111111111",
        updated_at=_NOW,
    )
    store.upsert_sync_state(state)
    loaded = store.get_sync_state("p1", "last_event_id")
    assert loaded is not None
    assert loaded.value_text == "11111111-1111-1111-1111-111111111111"


def test_real_store_sync_state_int_payload_and_idempotent(tmp_path: Path) -> None:
    """schema_version uses value_int; re-upsert on the same PK updates in place."""
    store = FactStore(StateBackendFactRepository(tmp_path))
    store.upsert_sync_state(
        SyncState(project_key="p1", key="schema_version", value_int=3, updated_at=_NOW)
    )
    store.upsert_sync_state(
        SyncState(project_key="p1", key="schema_version", value_int=4, updated_at=_LATER)
    )
    loaded = store.get_sync_state("p1", "schema_version")
    assert loaded is not None
    assert loaded.value_int == 4
