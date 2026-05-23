"""KpiAnalytics top-level class — the public surface of the kpi_analytics BC.

This is the facade described in bc-cut-decisions.md §BC 16 and FK-60 §60.1.
FactStore and RefreshWorker are optional dependencies injected at construction
time; missing dependencies produce explicit SKIPPED/error responses (FAIL CLOSED
— no silent empty returns).

AG3-029 Pass-3: signatures aligned to BC-16 §BC 16 Z. 1579 (W-A fix):
- refresh_analytics(project_key, hint_story_id=None) -> RefreshResult
- query(project_key, sql) -> KpiResult  # raw SQL; AG3-038-FOLLOWUP for typed API
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.kpi_analytics.errors import AnalyticsNotConfiguredError
from agentkit.kpi_analytics.views import (
    DashboardView,
    DesignTokens,
    KpiResult,
    RefreshResult,
    RefreshStatus,
)

if TYPE_CHECKING:
    from agentkit.kpi_analytics.catalog import KpiCatalog, KpiDefinition


class KpiAnalytics:
    """Top-level facade for the KpiAnalytics bounded context (FK-60 §60.1).

    Orchestrates KPI catalog access, analytics refresh, dashboard views,
    KPI queries, and design token retrieval. All operations that require
    FactStore or RefreshWorker will fail explicitly if those dependencies
    are absent — never silently returning empty data.

    BC-16 Top-Surface (bc-cut-decisions.md §BC 16 Z. 1579):
    - list_kpis() -> list[KpiDefinition]
    - refresh_analytics(project_key, hint_story_id=None) -> RefreshResult
    - get_dashboard_view(project_key, view_kind) -> DashboardView
    - query(project_key, sql) -> KpiResult  # AG3-038-FOLLOWUP: typed query API
    - get_design_tokens() -> DesignTokens

    Args:
        catalog: The KpiCatalog providing KPI definitions.
        fact_store: Optional FactStore adapter (AG3-038). When ``None``,
            operations requiring it raise ``AnalyticsNotConfiguredError``.
        refresh_worker: Optional RefreshWorker (follow-up story after AG3-038).
            When ``None``, ``refresh_analytics`` returns ``SKIPPED``.
    """

    def __init__(
        self,
        catalog: KpiCatalog,
        fact_store: object | None = None,
        refresh_worker: object | None = None,
    ) -> None:
        self._catalog = catalog
        self._fact_store = fact_store
        self._refresh_worker = refresh_worker

    def list_kpis(self) -> list[KpiDefinition]:
        """Return all KPI definitions from the catalog.

        Returns:
            Snapshot of all registered KpiDefinition entries.
            May be incomplete while ``catalog.catalog_status == SKELETON``.
        """
        return self._catalog.list_definitions()

    def refresh_analytics(
        self,
        project_key: str,
        hint_story_id: str | None = None,
    ) -> RefreshResult:
        """Trigger an analytics refresh for the given project.

        BC-16 §BC 16 Z. 1581: ``refresh_analytics(project_key, hint_story_id=None)``.
        When FactStore or RefreshWorker are not configured, returns an explicit
        SKIPPED result. No silent success — FAIL CLOSED per AG3-029 deep-review.

        Args:
            project_key: Project scope for the refresh.
            hint_story_id: Optional story scope hint for the refresh.
                ``None`` refreshes all dirty facts for the project.

        Returns:
            RefreshResult with status SKIPPED (no infrastructure), OK or FAILED.
        """
        if self._fact_store is None or self._refresh_worker is None:
            return RefreshResult(
                status=RefreshStatus.SKIPPED,
                reason="fact_store_or_refresh_worker_not_configured",
                refreshed_facts=0,
                errors=[],
            )
        del project_key, hint_story_id
        raise NotImplementedError(  # pragma: no cover
            "KpiAnalytics.refresh_analytics full path requires FactStore + RefreshWorker"
        )

    def get_dashboard_view(self, project_key: str, view_kind: str) -> DashboardView:
        """Retrieve a named dashboard view.

        BC-16 §BC 16 Z. 1582: ``get_dashboard_view(project_key, view_kind)``.
        When FactStore is not configured, raises AnalyticsNotConfiguredError.

        Args:
            project_key: Project scope.
            view_kind: Identifier of the requested dashboard view kind.

        Returns:
            DashboardView payload.

        Raises:
            AnalyticsNotConfiguredError: When FactStore is not configured.
        """
        if self._fact_store is None:
            raise AnalyticsNotConfiguredError(
                "DashboardView requires FactStore; implemented in AG3-038+"
            )
        del project_key, view_kind
        raise NotImplementedError(  # pragma: no cover
            "KpiAnalytics.get_dashboard_view full path requires FactStore"
        )

    def query(self, project_key: str, sql: str) -> KpiResult:
        """Query KPI data via raw SQL (Query-Workbench).

        BC-16 §BC 16 Z. 1583: ``query(project_key, sql) -> QueryResult``.
        AG3-038-FOLLOWUP: raw SQL is a security risk — the follow-up story
        must deliver a typed KPI query API instead of raw SQL to avoid
        injection and to support safe projection onto KpiResult.

        Args:
            project_key: Project scope.
            sql: Raw SQL query string (temporary; see AG3-038-FOLLOWUP above).

        Raises:
            NotImplementedError: Always, until AG3-038 is delivered.
        """
        raise NotImplementedError(
            "KpiAnalytics.query is part of follow-up story for FactStore + RefreshWorker"
        )

    def get_design_tokens(self) -> DesignTokens:
        """Return dashboard design tokens (FK-64 DesignSystem).

        Not implemented in AG3-029 — DesignSystem is a separate follow-up story.
        Hard-fail chosen over empty tokens: empty tokens would falsely suggest the
        system is configured (AG3-029 deep-review).

        Raises:
            NotImplementedError: Always, until the DesignSystem follow-up story.
        """
        raise NotImplementedError(
            "DesignSystem tokens are implemented in follow-up story (FK-64)"
        )
