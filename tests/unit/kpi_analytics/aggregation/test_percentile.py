"""Unit tests for the pure ``percentile`` helper (FK-62 §62.3.6, story AC9).

``percentile`` is a pure A-bloodtype function with NO persistence: AG3-082 tests
the computation fully but never writes a p50/p95 column (that is AG3-083 scope,
``_STORY_INDEX.md`` line 89, after AG3-082). These tests assert the linear
interpolation at support points + the empty/single-value edge cases.
"""

from __future__ import annotations

from agentkit.backend.kpi_analytics.aggregation import percentile


def test_empty_input_returns_none() -> None:
    assert percentile([], 50) is None
    assert percentile([], 95) is None


def test_single_value_returns_that_value() -> None:
    assert percentile([42.0], 50) == 42.0
    assert percentile([42.0], 95) == 42.0


def test_p50_is_the_median_of_an_odd_sample() -> None:
    # n=5 -> k = 4 * 0.5 = 2.0 -> exact order statistic index 2.
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0


def test_p50_interpolates_between_two_middle_values() -> None:
    # n=4 -> k = 3 * 0.5 = 1.5 -> halfway between values[1]=2 and values[2]=3.
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5


def test_p95_interpolates_near_the_top() -> None:
    # n=11 -> k = 10 * 0.95 = 9.5 -> halfway between values[9]=10 and values[10]=11.
    values = [float(v) for v in range(1, 12)]
    assert percentile(values, 95) == 10.5


def test_input_order_is_irrelevant() -> None:
    assert percentile([5.0, 1.0, 3.0, 2.0, 4.0], 50) == 3.0


def test_p100_returns_the_maximum() -> None:
    assert percentile([1.0, 2.0, 9.0], 100) == 9.0


def test_p0_returns_the_minimum() -> None:
    assert percentile([4.0, 1.0, 9.0], 0) == 1.0
