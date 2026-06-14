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

from agentkit.kpi_analytics.design_system import get_design_system
from agentkit.kpi_analytics.errors import AnalyticsNotConfiguredError
from agentkit.kpi_analytics.views import (
    DashboardView,
    DashboardViewStatus,
    DesignTokens,
    KpiResult,
    RefreshResult,
    RefreshStatus,
)

if TYPE_CHECKING:
    from agentkit.kpi_analytics.aggregation import RefreshWorker
    from agentkit.kpi_analytics.catalog import KpiCatalog, KpiDefinition
    from agentkit.kpi_analytics.fact_store import FactStore


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
        refresh_worker: Optional RefreshWorker (AG3-082). When ``None`` (or when
            ``fact_store`` is ``None``), ``refresh_analytics`` returns ``SKIPPED``.
    """

    def __init__(
        self,
        catalog: KpiCatalog,
        fact_store: FactStore | None = None,
        refresh_worker: RefreshWorker | None = None,
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

        AG3-082: when both dependencies are configured, this is the Closure adapter
        onto the real RefreshWorker — it calls ``sync_analytics`` with
        ``trigger=RefreshTrigger.CLOSURE`` (FK-62 §62.3.1 primary trigger) without
        information loss. The Dashboard catch-up and Reset triggers are set by their
        own callers (dashboard start / ``purge_story_analytics``), not through this
        facade path (story §2.1.2).

        Args:
            project_key: Project scope for the refresh.
            hint_story_id: Optional story scope hint for the refresh.
                ``None`` refreshes all dirty facts for the project.

        Returns:
            RefreshResult with status SKIPPED (no infrastructure) or OK.
        """
        if self._fact_store is None or self._refresh_worker is None:
            return RefreshResult(
                status=RefreshStatus.SKIPPED,
                reason="fact_store_or_refresh_worker_not_configured",
                refreshed_facts=0,
                errors=[],
            )
        from agentkit.kpi_analytics.aggregation import RefreshTrigger

        result = self._refresh_worker.sync_analytics(
            RefreshTrigger.CLOSURE,
            project_key,
            hint_story_id,
        )
        return RefreshResult(
            status=RefreshStatus.OK,
            reason=result.status.value,
            refreshed_facts=result.events_processed,
            errors=[],
        )

    def get_dashboard_view(self, project_key: str, view_kind: str) -> DashboardView:
        """Retrieve a named dashboard view by reading FactStore (AG3-038).

        BC-16 §BC 16 Z. 1582: ``get_dashboard_view(project_key, view_kind)``.
        When FactStore is not configured, raises AnalyticsNotConfiguredError.

        AG3-038 wires the ``story`` view kind onto the real ``fact_story`` read
        path: it returns one row per completed story for ``project_key``. An
        empty result yields an EMPTY view (status OK) — never a hardcoded empty
        stub. FAIL-CLOSED (story §7): a missing fact table propagates the
        repository error rather than degrading to an empty view. Other view
        kinds (period rollups) are delivered by the follow-up RefreshWorker
        story; requesting one now fails closed with NotImplementedError rather
        than silently returning empty data.

        Args:
            project_key: Project scope.
            view_kind: Identifier of the requested dashboard view kind. ``story``
                is wired in AG3-038; others are follow-up.

        Returns:
            DashboardView payload populated from FactStore (rows empty only when
            the underlying fact data is genuinely empty).

        Raises:
            AnalyticsNotConfiguredError: When FactStore is not configured.
            NotImplementedError: For view kinds not yet wired (period rollups).
        """
        if self._fact_store is None:
            raise AnalyticsNotConfiguredError(
                "DashboardView requires FactStore; implemented in AG3-038+"
            )
        if view_kind != "story":
            raise NotImplementedError(
                f"DashboardView kind {view_kind!r} requires the RefreshWorker "
                "follow-up story; only 'story' is wired in AG3-038"
            )
        facts = self._fact_store.list_fact_stories(project_key)
        rows: list[dict[str, object]] = [
            fact.model_dump(mode="json") for fact in facts
        ]
        return DashboardView(
            view_name=view_kind,
            project_key=project_key,
            status=DashboardViewStatus.OK,
            rows=rows,
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
        """Return the typed dashboard design token set (FK-64 §64.2, AG3-092).

        Delivers the authoritative ``DesignSystem`` token owner as a
        wire-serializable ``DesignTokens`` view.  The token set is deterministic
        and has no runtime dependencies.

        Replaces the ``NotImplementedError`` stub from AG3-029.

        Returns:
            ``DesignTokens`` with the full typed family tree (colors / typography
            / spacing / control / chart).
        """
        ds = get_design_system()
        return DesignTokens(
            colors=ds.colors,
            typography=ds.typography,
            spacing=ds.spacing,
            control=ds.control,
            chart=ds.chart,
        )
