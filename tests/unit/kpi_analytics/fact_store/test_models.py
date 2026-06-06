"""Unit tests for the analytics fact-record Pydantic models (AG3-038 AC4).

Pins the frozen / extra=forbid contract and the required-vs-optional field shape
of every fact record + SyncState + PeriodFilter (FK-62 §62.2, story §2.1.1).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.kpi_analytics.fact_store.models import (
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
        started_at=_NOW,
        qa_rounds=3,
        agentkit_version="3.19.0",
        agentkit_commit="deadbeef",
    )


def test_fact_story_minimal_required_fields_and_optional_defaults() -> None:
    fact = _fact_story()
    assert fact.story_mode is None
    assert fact.completed_at is None
    assert fact.feedback_converged is None
    assert fact.qa_rounds == 3


def test_fact_story_is_frozen() -> None:
    fact = _fact_story()
    with pytest.raises(ValidationError):
        fact.qa_rounds = 4  # type: ignore[misc]


def test_fact_story_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        FactStory(
            project_key="p1",
            story_id="AG3-001",
            story_type="implementation",
            story_size="L",
            started_at=_NOW,
            qa_rounds=3,
            agentkit_version="3.19.0",
            agentkit_commit="deadbeef",
            unexpected="x",  # type: ignore[call-arg]
        )


def test_fact_story_missing_required_field_raises() -> None:
    with pytest.raises(ValidationError):
        FactStory(  # type: ignore[call-arg]
            project_key="p1",
            story_id="AG3-001",
            story_type="implementation",
            story_size="L",
            started_at=_NOW,
            qa_rounds=3,
            agentkit_version="3.19.0",
            # agentkit_commit missing
        )


def test_fact_guard_period_roundtrips() -> None:
    fact = FactGuardPeriod(
        project_key="p1",
        guard_id="changed-file-policy",
        period_start=_NOW,
        period_end=_LATER,
        invocation_count=10,
        violation_count=2,
    )
    assert fact.invocation_count == 10
    with pytest.raises(ValidationError):
        fact.invocation_count = 11  # type: ignore[misc]


def test_fact_pool_period_optional_latency() -> None:
    fact = FactPoolPeriod(
        project_key="p1",
        llm_role="worker",
        period_start=_NOW,
        period_end=_LATER,
        call_count=5,
        token_input_total=100,
        token_output_total=50,
    )
    assert fact.avg_latency_ms is None


def test_fact_pipeline_period_optional_averages() -> None:
    fact = FactPipelinePeriod(
        project_key="p1",
        period_start=_NOW,
        period_end=_LATER,
        stories_completed=4,
        stories_escalated=1,
    )
    assert fact.avg_qa_rounds is None
    assert fact.avg_phase_implementation_ms is None


def test_fact_corpus_period_required_counts() -> None:
    fact = FactCorpusPeriod(
        project_key="p1",
        period_start=_NOW,
        period_end=_LATER,
        incidents_recorded=2,
        patterns_promoted=1,
        checks_approved=1,
    )
    assert fact.incidents_recorded == 2


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
