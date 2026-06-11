"""Aggregation sub-package — the analytics RefreshWorker (FK-62 §62.3).

Public surface of the recompute half of the FK-62 Refresh-Worker: the
``RefreshWorker`` (``sync_analytics`` / ``purge_story_analytics``), the typed
trigger/result/dirty-set contracts, the consumer-owned runtime read port
(``AnalyticsSourcePort``), and the pure ``percentile`` helper. The AG3-081 hot-path
counter writer and FK-69 read-model purge port are CONSUMED through the read port,
not rebuilt here (story §2.2).
"""

from __future__ import annotations

from agentkit.kpi_analytics.aggregation.dirty_sets import (
    DirtySets,
    derive_dirty_sets,
    month_start_for,
)
from agentkit.kpi_analytics.aggregation.models import (
    AffectedPeriods,
    RefreshTrigger,
    SyncResult,
    SyncStatus,
)
from agentkit.kpi_analytics.aggregation.percentile import percentile
from agentkit.kpi_analytics.aggregation.source_port import (
    AnalyticsSourcePort,
    DeltaEvent,
)
from agentkit.kpi_analytics.aggregation.worker import (
    EXPECTED_SCHEMA_VERSION,
    RefreshWorker,
)

__all__ = [
    "EXPECTED_SCHEMA_VERSION",
    "AffectedPeriods",
    "AnalyticsSourcePort",
    "DeltaEvent",
    "DirtySets",
    "RefreshTrigger",
    "RefreshWorker",
    "SyncResult",
    "SyncStatus",
    "derive_dirty_sets",
    "month_start_for",
    "percentile",
]
