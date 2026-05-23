"""Typed exceptions for the kpi_analytics bounded context."""

from __future__ import annotations


class AnalyticsNotConfiguredError(Exception):
    """Raised when a KpiAnalytics operation requires FactStore but none is configured.

    This exception signals that the analytics infrastructure (FactStore,
    RefreshWorker) is not yet available. Consumers must treat this as a
    hard configuration failure, not a data-not-found condition.
    """
