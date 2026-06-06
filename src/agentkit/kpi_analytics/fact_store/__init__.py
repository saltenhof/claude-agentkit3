"""FactStore sub-package (FK-62 §62.3, story AG3-038 §2.1.2).

Public surface of the analytics fact-store: the :class:`FactStore` driver, the
consumer-owned :class:`FactRepository` persistence Protocol (AC8 import
boundary), and the frozen Pydantic fact-record models.
"""

from __future__ import annotations

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
from agentkit.kpi_analytics.fact_store.repository import FactRepository
from agentkit.kpi_analytics.fact_store.store import FactStore

__all__ = [
    "FactCorpusPeriod",
    "FactGuardPeriod",
    "FactPipelinePeriod",
    "FactPoolPeriod",
    "FactRepository",
    "FactStore",
    "FactStory",
    "GuardInvocationCounter",
    "PeriodFilter",
    "SyncState",
]
