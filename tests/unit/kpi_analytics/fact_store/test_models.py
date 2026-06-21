"""Unit tests for the analytics fact-record Pydantic models (AG3-038 AC4).

Pins the frozen / extra=forbid contract and the required-vs-optional field shape
of every fact record + SyncState + PeriodFilter (FK-62 §62.2, story §2.1.1).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.backend.kpi_analytics.fact_store.models import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStory,
    GuardInvocationCounter,
    PeriodFilter,
    SyncState,
)

_NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
_LATER = datetime(2026, 6, 12, 12, 0, tzinfo=UTC)


def _fact_story() -> FactStory:
    return FactStory(
        project_key="p1",
        story_id="AG3-001",
        story_type="implementation",
        story_size="L",
        opened_at=_NOW,
        qa_round_count=3,
        computed_at=_LATER,
    )


def test_fact_story_minimal_required_fields_and_optional_defaults() -> None:
    fact = _fact_story()
    assert fact.pipeline_mode is None
    assert fact.closed_at is None
    assert fact.feedback_converged is None
    assert fact.are_gate_passed is None
    assert fact.qa_round_count == 3
    # FK-62 NOT NULL DEFAULT 0 columns default to 0 on the typed record.
    assert fact.compaction_count == 0
    assert fact.files_changed == 0
    assert fact.increment_count == 0


def test_fact_story_is_frozen() -> None:
    fact = _fact_story()
    with pytest.raises(ValidationError):
        fact.qa_round_count = 4  # type: ignore[misc]


def test_fact_story_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        FactStory(
            project_key="p1",
            story_id="AG3-001",
            story_type="implementation",
            story_size="L",
            opened_at=_NOW,
            qa_round_count=3,
            computed_at=_LATER,
            unexpected="x",  # type: ignore[call-arg]
        )


def test_fact_story_missing_required_field_raises() -> None:
    with pytest.raises(ValidationError):
        FactStory(  # type: ignore[call-arg]
            project_key="p1",
            story_id="AG3-001",
            story_type="implementation",
            story_size="L",
            opened_at=_NOW,
            qa_round_count=3,
            # computed_at missing (FK-62 NOT NULL)
        )


def test_fact_story_are_gate_passed_is_bool() -> None:
    """AG3-117 R2: are_gate_passed is a real bool (FK-62 §62.2.1 INTEGER)."""
    fact = FactStory(
        project_key="p1",
        story_id="AG3-001",
        story_type="implementation",
        story_size="L",
        opened_at=_NOW,
        qa_round_count=0,
        are_gate_passed=True,
        computed_at=_LATER,
    )
    assert fact.are_gate_passed is True


def test_fact_guard_period_roundtrips() -> None:
    fact = FactGuardPeriod(
        project_key="p1",
        guard_key="changed-file-policy",
        period_start=_NOW,
        invocation_count=10,
        violation_count=2,
        computed_at=_LATER,
    )
    assert fact.invocation_count == 10
    assert fact.period_grain == "week"
    with pytest.raises(ValidationError):
        fact.invocation_count = 11  # type: ignore[misc]


def test_fact_pool_period_optional_p50() -> None:
    fact = FactPoolPeriod(
        project_key="p1",
        pool_key="worker",
        period_start=_NOW,
        call_count=5,
        computed_at=_LATER,
    )
    assert fact.response_time_p50_ms is None
    assert fact.period_grain == "week"


def test_fact_pipeline_period_optional_averages() -> None:
    fact = FactPipelinePeriod(
        project_key="p1",
        period_start=_NOW,
        story_count=4,
        story_count_closed=3,
        computed_at=_LATER,
    )
    assert fact.qa_round_avg is None
    assert fact.processing_time_avg_ms is None
    assert fact.period_grain == "week"


def test_fact_corpus_period_required_counts() -> None:
    fact = FactCorpusPeriod(
        project_key="p1",
        period_start=_NOW,
        new_incident_count=2,
        patterns_total_count=1,
        patterns_with_active_check=1,
        computed_at=_LATER,
    )
    assert fact.new_incident_count == 2
    assert fact.period_grain == "month"


def test_sync_state_is_project_scoped_key_value() -> None:
    """FK-62 §62.2.7: (project_key, key) cursor with two payload slots."""
    state = SyncState(project_key="p1", key="last_event_id", updated_at=_NOW)
    assert state.value_int is None
    assert state.value_text is None
    assert state.project_key == "p1"
    assert state.key == "last_event_id"
    with pytest.raises(ValidationError):
        SyncState(  # type: ignore[call-arg]
            project_key="p1",
            key="last_event_id",
            updated_at=_NOW,
            bogus=1,
        )


def test_guard_invocation_counter_weekly_scratchpad_shape() -> None:
    """FK-62 §62.2.6 / FK-61 §61.4.3: weekly-keyed invocations/blocks counter."""
    counter = GuardInvocationCounter(
        project_key="p1",
        story_id="AG3-001",
        guard_key="changed-file-policy",
        week_start="2026-06-01",
        invocations=42,
        blocks=3,
        updated_at=_NOW,
    )
    assert counter.invocations == 42
    assert counter.blocks == 3
    with pytest.raises(ValidationError):
        counter.invocations = 43  # type: ignore[misc]


def test_guard_invocation_counter_defaults_to_zero() -> None:
    counter = GuardInvocationCounter(
        project_key="p1",
        story_id="AG3-001",
        guard_key="g1",
        week_start="2026-06-01",
        updated_at=_NOW,
    )
    assert counter.invocations == 0
    assert counter.blocks == 0


def test_period_filter_holds_bounds() -> None:
    period = PeriodFilter(start=_NOW, end=_LATER)
    assert period.start == _NOW
    assert period.end == _LATER
