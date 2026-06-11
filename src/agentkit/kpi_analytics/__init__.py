"""KpiAnalytics bounded context — public re-exports (bc-cut-decisions.md §BC 16).

This package is the top-level surface for all KPI analytics functionality.
The full implementation (FactStore, RefreshWorker, 40 KPI definitions) is
built incrementally across follow-up stories (AG3-038 and beyond).
"""

from __future__ import annotations

from agentkit.kpi_analytics.aggregation import (
    AffectedPeriods,
    RefreshTrigger,
    RefreshWorker,
)
from agentkit.kpi_analytics.catalog import (
    KpiCatalog,
    KpiCollectionPoint,
    KpiDefinition,
    KpiDomain,
    KpiGranularity,
)
from agentkit.kpi_analytics.fact_store.guard_counter import (
    GuardCounterService,
    week_start_for,
)
from agentkit.kpi_analytics.top import KpiAnalytics
from agentkit.kpi_analytics.views import DashboardView

__all__ = [
    "AffectedPeriods",
    "DashboardView",
    "GuardCounterService",
    "KpiAnalytics",
    "KpiCatalog",
    "KpiCollectionPoint",
    "KpiDefinition",
    "KpiDomain",
    "KpiGranularity",
    "RefreshTrigger",
    "RefreshWorker",
    "week_start_for",
]
