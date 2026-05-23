"""View models and status enums for the kpi_analytics bounded context."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class RefreshStatus(StrEnum):
    """Outcome status of a KPI analytics refresh operation."""

    OK = "OK"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class DashboardViewStatus(StrEnum):
    """Availability status of a dashboard view."""

    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"


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
    rows: list[dict[str, object]]


class DesignTokens(BaseModel):
    """Design tokens for the KPI dashboard frontend.

    Stub for AG3-029. Full implementation is a follow-up story (FK-64 DesignSystem).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tokens: dict[str, str] = {}
