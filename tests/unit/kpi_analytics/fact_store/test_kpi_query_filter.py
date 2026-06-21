"""Unit tests for KpiQueryFilter (AG3-084, FK-63 §63.3.3/§63.4.2).

Covers:
- Valid filter construction.
- Fail-closed validation for reversed period, period overlap, mutual exclusion.
- story_filter and entity_filter optional fields.
- comparison_period constraints.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.backend.kpi_analytics.fact_store.models import (
    EntityFilter,
    KpiQueryFilter,
    PeriodFilter,
    StoryFilter,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)
_END = datetime(2026, 6, 1, tzinfo=UTC)
_COMP_START = datetime(2025, 7, 1, tzinfo=UTC)
_COMP_END = datetime(2025, 12, 31, tzinfo=UTC)
_PROJECT = "tenant-a"


# ---------------------------------------------------------------------------
# Valid constructions
# ---------------------------------------------------------------------------


def test_minimal_valid_filter() -> None:
    """A KpiQueryFilter with only project_key + period is valid."""
    f = KpiQueryFilter(
        project_key=_PROJECT,
        period=PeriodFilter(start=_START, end=_END),
    )
    assert f.project_key == _PROJECT
    assert f.period.start == _START
    assert f.period.end == _END
    assert f.entity_filter.guard is None
    assert f.entity_filter.pool is None
    assert f.story_filter.story_type is None
    assert f.story_filter.story_size is None
    assert f.comparison_period is None


def test_full_filter_with_all_fields() -> None:
    """All optional fields can be populated without error."""
    f = KpiQueryFilter(
        project_key=_PROJECT,
        period=PeriodFilter(start=_START, end=_END),
        entity_filter=EntityFilter(guard="changed-file-policy"),
        story_filter=StoryFilter(story_type="implementation", story_size="L"),
        comparison_period=PeriodFilter(start=_COMP_START, end=_COMP_END),
    )
    assert f.entity_filter.guard == "changed-file-policy"
    assert f.story_filter.story_type == "implementation"
    assert f.comparison_period is not None
    assert f.comparison_period.end == _COMP_END


def test_pool_entity_filter_is_valid() -> None:
    """entity_filter.pool without guard is valid."""
    f = KpiQueryFilter(
        project_key=_PROJECT,
        period=PeriodFilter(start=_START, end=_END),
        entity_filter=EntityFilter(pool="qa"),
    )
    assert f.entity_filter.pool == "qa"
    assert f.entity_filter.guard is None


# ---------------------------------------------------------------------------
# Fail-closed: reversed / equal period
# ---------------------------------------------------------------------------


def test_reversed_period_rejected() -> None:
    """period.start >= period.end must be rejected (fail-closed)."""
    with pytest.raises(ValidationError, match="start must be < period.end"):
        KpiQueryFilter(
            project_key=_PROJECT,
            period=PeriodFilter(start=_END, end=_START),
        )


def test_equal_period_bounds_rejected() -> None:
    """period.start == period.end is a zero-width window — rejected."""
    with pytest.raises(ValidationError, match="start must be < period.end"):
        KpiQueryFilter(
            project_key=_PROJECT,
            period=PeriodFilter(start=_START, end=_START),
        )


# ---------------------------------------------------------------------------
# Fail-closed: entity_filter mutual exclusion
# ---------------------------------------------------------------------------


def test_guard_and_pool_both_set_rejected() -> None:
    """guard and pool are mutually exclusive (contradictory for one KPI dimension)."""
    with pytest.raises(ValidationError, match="mutually exclusive"):
        KpiQueryFilter(
            project_key=_PROJECT,
            period=PeriodFilter(start=_START, end=_END),
            entity_filter=EntityFilter(guard="changed-file-policy", pool="qa"),
        )


# ---------------------------------------------------------------------------
# Fail-closed: comparison_period constraints
# ---------------------------------------------------------------------------


def test_comparison_period_after_main_period_rejected() -> None:
    """comparison_period must end at or before period.start (no overlap)."""
    with pytest.raises(ValidationError, match="end at or before period.start"):
        KpiQueryFilter(
            project_key=_PROJECT,
            period=PeriodFilter(start=_START, end=_END),
            # comparison_period overlaps with period (end > period.start).
            comparison_period=PeriodFilter(
                start=datetime(2025, 12, 1, tzinfo=UTC),
                end=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        )


def test_comparison_period_reversed_rejected() -> None:
    """comparison_period with start >= end must be rejected."""
    with pytest.raises(ValidationError, match="start must be < comparison_period.end"):
        KpiQueryFilter(
            project_key=_PROJECT,
            period=PeriodFilter(start=_START, end=_END),
            comparison_period=PeriodFilter(start=_COMP_END, end=_COMP_START),
        )


def test_comparison_period_exactly_at_period_start_is_valid() -> None:
    """comparison_period.end == period.start is valid (contiguous, non-overlapping)."""
    f = KpiQueryFilter(
        project_key=_PROJECT,
        period=PeriodFilter(start=_START, end=_END),
        comparison_period=PeriodFilter(
            start=_COMP_START,
            end=_START,  # exactly at period.start (contiguous)
        ),
    )
    assert f.comparison_period is not None
    assert f.comparison_period.end == _START


# ---------------------------------------------------------------------------
# Fail-closed: naive ISO string is rejected (mode="after" validator fix)
# ---------------------------------------------------------------------------


def test_period_filter_rejects_naive_iso_string_start() -> None:
    """PeriodFilter must reject a naive ISO-8601 string for start (no tz offset).

    This is the case that the old mode='before' validator missed: Pydantic
    parsed the string into a naive datetime AFTER the before-validator ran,
    so the tzinfo check was never reached.  The mode='after' fix closes this.
    """
    with pytest.raises((ValueError, Exception), match="timezone-aware"):
        PeriodFilter(
            start="2026-01-01T00:00:00",  # naive ISO string — no Z, no offset
            end=_END,
        )


def test_period_filter_rejects_naive_iso_string_end() -> None:
    """PeriodFilter must reject a naive ISO-8601 string for end (no tz offset)."""
    with pytest.raises((ValueError, Exception), match="timezone-aware"):
        PeriodFilter(
            start=_START,
            end="2026-06-01T00:00:00",  # naive ISO string — no Z, no offset
        )


def test_kpi_query_filter_rejects_naive_iso_string_in_period() -> None:
    """KpiQueryFilter.period must reject a naive ISO string (covers both period and comparison_period).

    This is the contract-level test for the PeriodFilter mode='after' fix
    that prevents naive datetimes from slipping through when input is a string.
    """
    with pytest.raises((ValueError, Exception), match="timezone-aware"):
        KpiQueryFilter(
            project_key=_PROJECT,
            period=PeriodFilter(
                start="2026-01-01T00:00:00",  # naive ISO string
                end=_END,
            ),
        )


def test_kpi_query_filter_rejects_naive_iso_string_in_comparison_period() -> None:
    """KpiQueryFilter.comparison_period must reject a naive ISO string."""
    with pytest.raises((ValueError, Exception), match="timezone-aware"):
        KpiQueryFilter(
            project_key=_PROJECT,
            period=PeriodFilter(start=_START, end=_END),
            comparison_period=PeriodFilter(
                start="2025-07-01T00:00:00",  # naive ISO string
                end=_COMP_END,
            ),
        )
