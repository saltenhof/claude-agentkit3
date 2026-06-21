"""Percentile helper for the analytics RefreshWorker (FK-62 §62.3.6).

A pure, dependency-free percentile over a value list using linear interpolation
between the two nearest order statistics. FK-62 §62.3.6 pins this exact shape:
``numpy``/``scipy`` are intentionally NOT used (the analytics slices carry
10-100 values, so the lightweight interpolation is sufficient and avoids a heavy
dependency, FK-62 §62.3.6).

This module is an A-bloodtype pure function (no I/O, no side effects, no
persistence). AG3-082 implements and tests ``percentile`` fully but does NOT
persist its result: the ``response_time_p50_ms`` write column is AG3-083 scope
(``_STORY_INDEX.md`` line 89, after AG3-082), and ``response_time_p95_ms`` stays
inventory (FK-62 §62.2.3). There is deliberately no p50/p95 write path here.
"""

from __future__ import annotations


def percentile(values: list[float], p: int) -> float | None:
    """Return the ``p``-th percentile of ``values`` via linear interpolation.

    FK-62 §62.3.6 verbatim algorithm. The rank ``k = (n - 1) * (p / 100)`` is the
    fractional index into the sorted values; the result interpolates linearly
    between ``values[floor(k)]`` and ``values[floor(k) + 1]``.

    Args:
        values: The sample values (order irrelevant; sorted internally). May be
            empty.
        p: The percentile to compute (e.g. ``50`` for P50, ``95`` for P95).

    Returns:
        ``None`` for an empty input (FK-62 §62.3.6: no value to report); the lone
        value for a single-element input; otherwise the linearly interpolated
        percentile.
    """
    if not values:
        return None
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100)
    f = int(k)
    c = f + 1
    if c >= len(sorted_vals):
        return sorted_vals[f]
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])


__all__ = ["percentile"]
