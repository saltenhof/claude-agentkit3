"""Integration roundtrip for the analytics fact store (AG3-038 §2.1.7).

End-to-end against a real on-disk SQLite database (the test-parallel backend;
Postgres canonical roundtrip lives in the contract test): the MigrationRunner
bootstraps the analytics tables, the FactStore inserts one row into ALL FIVE fact
tables plus sync_state, and reads them back through the typed read API. Pinned to
SQLite (autouse) so the suite stays Docker-free.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.kpi_analytics.fact_store import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStore,
    FactStory,
    PeriodFilter,
    SyncState,
)
from agentkit.backend.state_backend.store.fact_repository import StateBackendFactRepository

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
_LATER = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)
_PERIOD = PeriodFilter(start=_NOW, end=datetime(2026, 7, 1, tzinfo=UTC))


@pytest.fixture(autouse=True)
def _pin_sqlite(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin SQLite so a leaked Postgres env cannot route this Docker-free test."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def test_full_five_table_roundtrip_plus_sync_state(tmp_path: Path) -> None:
    store = FactStore(StateBackendFactRepository(store_dir=tmp_path))

    store.upsert_fact_story(
        FactStory(
            project_key="tenant-a",
            story_id="AG3-038",
            story_type="implementation",
            story_size="L",
            pipeline_mode="standard",
            opened_at=_NOW,
            closed_at=_LATER,
            qa_round_count=4,
            compaction_count=2,
            llm_call_count=18,
            adversarial_findings_count=3,
            adversarial_tests_created=5,
            files_changed=11,
            feedback_converged=True,
            phase_setup_ms=1200,
            phase_implementation_ms=45000,
            phase_closure_ms=900,
            are_gate_passed=True,
            computed_at=_LATER,
        )
    )
    store.upsert_fact_guard(
        FactGuardPeriod(
            project_key="tenant-a",
            guard_key="changed-file-policy",
            period_start=_NOW,
            invocation_count=42,
            violation_count=3,
            computed_at=_LATER,
        )
    )
    store.upsert_fact_pool(
        FactPoolPeriod(
            project_key="tenant-a",
            pool_key="qa",
            period_start=_NOW,
            call_count=8,
            response_time_p50_ms=820,
            computed_at=_LATER,
        )
    )
    store.upsert_fact_pipeline(
        FactPipelinePeriod(
            project_key="tenant-a",
            period_start=_NOW,
            story_count=7,
            story_count_closed=6,
            qa_round_avg=2.83,
            processing_time_avg_ms=39000,
            computed_at=_LATER,
        )
    )
    store.upsert_fact_corpus(
        FactCorpusPeriod(
            project_key="tenant-a",
            period_start=_NOW,
            new_incident_count=4,
            patterns_total_count=2,
            patterns_with_active_check=1,
            computed_at=_LATER,
        )
    )
    store.upsert_sync_state(
        SyncState(
            project_key="tenant-a",
            key="last_event_id",
            value_text="33333333-3333-3333-3333-333333333333",
            updated_at=_LATER,
        )
    )

    story = store.list_fact_stories("tenant-a")[0]
    assert story.are_gate_passed is True
    assert story.phase_implementation_ms == 45000
    assert story.adversarial_tests_created == 5

    assert store.list_fact_guards("tenant-a", _PERIOD)[0].violation_count == 3
    assert store.list_fact_pool("tenant-a", _PERIOD)[0].response_time_p50_ms == 820
    pipeline = store.list_fact_pipeline("tenant-a", _PERIOD)[0]
    assert pipeline.processing_time_avg_ms == 39000
    assert store.list_fact_corpus("tenant-a", _PERIOD)[0].patterns_total_count == 2

    cursor = store.get_sync_state("tenant-a", "last_event_id")
    assert cursor is not None
    assert cursor.value_text == "33333333-3333-3333-3333-333333333333"


def test_tenant_isolation_leading_project_key(tmp_path: Path) -> None:
    """FK-62 Mandantenregel: reads are scoped to project_key."""
    store = FactStore(StateBackendFactRepository(store_dir=tmp_path))
    for tenant in ("tenant-a", "tenant-b"):
        store.upsert_fact_story(
            FactStory(
                project_key=tenant,
                story_id="AG3-001",
                story_type="implementation",
                story_size="S",
                opened_at=_NOW,
                qa_round_count=1,
                computed_at=_NOW,
            )
        )
    a_rows = store.list_fact_stories("tenant-a")
    assert [r.project_key for r in a_rows] == ["tenant-a"]
    assert len(store.list_fact_stories("tenant-b")) == 1
