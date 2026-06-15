"""View models and status enums for the kpi_analytics bounded context."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from agentkit.kpi_analytics.design_system import (
    ChartTokens,
    ColorTokens,
    ControlTokens,
    SpacingFamily,
    TypographyTokens,
)
from agentkit.kpi_analytics.fact_store.models import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStory,
)

# Type alias for the typed union of all five fact row types.
# Serialization to plain dicts happens only at the HTTP edge
# (kpi_analytics/http/routes.py via row.model_dump(mode="json")).
DashboardFactRow = FactStory | FactGuardPeriod | FactPoolPeriod | FactPipelinePeriod | FactCorpusPeriod


class RefreshStatus(StrEnum):
    """Outcome status of a KPI analytics refresh operation."""

    OK = "OK"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class DashboardViewStatus(StrEnum):
    """Availability status of a dashboard view."""

    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"
    EMPTY = "EMPTY"


class RefreshResult(BaseModel):
    """Result of a KpiAnalytics.refresh_analytics() call.

    SKIPPED is returned when FactStore or RefreshWorker are not configured —
    this is an explicit signal, not a silent empty-success.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RefreshStatus
    reason: str | None = None
    refreshed_facts: int
    errors: list[str]


class KpiResult(BaseModel):
    """Query result for a single KPI data point."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kpi_id: str
    project_key: str
    period: str
    value: float | None = None
    unit: str = ""


class DashboardView(BaseModel):
    """A named dashboard view payload.

    Stub model for AG3-029. Full implementation requires FactStore (AG3-038).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    view_name: str
    project_key: str
    status: DashboardViewStatus
    rows: list[DashboardFactRow]
    comparison_rows: list[DashboardFactRow] = []


class DesignTokens(BaseModel):
    """Design tokens for the KPI dashboard frontend (FK-64 §64.2).

    Wire-serializable container returned by ``KpiAnalytics.get_design_tokens``.
    The canonical typed token owner is ``DesignSystem`` (AG3-092); this model
    exposes the full typed family tree for the HTTP adapter layer.

    Each family field is the *same typed Pydantic model* that the ``DesignSystem``
    owner uses — no untyped ``dict[str, object]`` family fields.  Serialization
    to a plain dict happens only at the HTTP edge (``kpi_analytics/http/routes.py``
    via ``model_dump(mode="json")``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    colors: ColorTokens = ColorTokens()
    typography: TypographyTokens = TypographyTokens()
    spacing: SpacingFamily = SpacingFamily()
    control: ControlTokens = ControlTokens()
    chart: ChartTokens = ChartTokens()
