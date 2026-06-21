"""Dashboard sub-package of kpi_analytics.

Migrated from agentkit.dashboard (AG3-029). No re-export shims to the old
path — all consumers must update their imports (Zero Debt rule).
"""

from __future__ import annotations

from agentkit.backend.kpi_analytics.dashboard.models import (
    BoardColumn,
    DashboardBoardResponse,
    DashboardStoryMetricsItem,
    DashboardStoryMetricsResponse,
)
from agentkit.backend.kpi_analytics.dashboard.service import DashboardService

__all__ = [
    "BoardColumn",
    "DashboardBoardResponse",
    "DashboardService",
    "DashboardStoryMetricsItem",
    "DashboardStoryMetricsResponse",
]
