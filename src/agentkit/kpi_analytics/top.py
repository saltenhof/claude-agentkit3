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
    from agentkit.kpi_analytics.fact_store.models import FactStory, KpiQueryFilter, PeriodFilter
    from agentkit.kpi_analytics.views import DashboardFactRow


def _read_dimension_rows(
    fact_store: FactStore,
    project_key: str,
    view_kind: str,
    period: PeriodFilter,
    kpi_filter: KpiQueryFilter,
) -> list[DashboardFactRow]:
    """Read one period window from FactStore for the given dimension and apply entity/story filters.

    Shared by the primary read and the AC5 comparison read in
    ``get_dashboard_view_with_filter`` so that the filter logic stays DRY and the
    method complexity stays within budget.

    Args:
        fact_store: The FactStore to read from.
        project_key: Project scope.
        view_kind: One of ``story``, ``guards``, ``pools``, ``pipeline``, ``corpus``.
        period: The half-open ``[start, end)`` window to pass to the FactStore.
        kpi_filter: Applied for entity / story sub-filters.

    Returns:
        Typed fact model instances (serialization to plain dicts happens only at
        the HTTP edge via ``row.model_dump(mode='json')``).

    Raises:
        ValueError: For unknown view_kind values (fail-closed).
    """
    if view_kind == "story":
        facts = fact_store.list_fact_stories(project_key, period)
        return [fact for fact in facts if _story_matches_filter(fact, kpi_filter)]
    if view_kind == "guards":
        guard_facts = fact_store.list_fact_guards(project_key, period)
        return [
            fact
            for fact in guard_facts
            if kpi_filter.entity_filter.guard is None
            or fact.guard_key == kpi_filter.entity_filter.guard
        ]
    if view_kind == "pools":
        pool_facts = fact_store.list_fact_pool(project_key, period)
        return [
            fact
            for fact in pool_facts
            if kpi_filter.entity_filter.pool is None
            or fact.pool_key == kpi_filter.entity_filter.pool
        ]
    if view_kind == "pipeline":
        return list(fact_store.list_fact_pipeline(project_key, period))
    if view_kind == "corpus":
        return list(fact_store.list_fact_corpus(project_key, period))
    raise ValueError(
        f"Unknown view_kind {view_kind!r}; accepted: "
        "story, guards, pools, pipeline, corpus"
    )


def _story_matches_filter(fact: FactStory, kpi_filter: KpiQueryFilter) -> bool:
    """Return True when a FactStory row matches the story-attribute filter.

    Applies the ``story_filter`` sub-filter from a ``KpiQueryFilter``.  Both
    ``story_type`` and ``story_size`` are optional; a ``None`` value on the
    filter means "accept any".

    Args:
        fact: A ``FactStory`` row from the fact table.
        kpi_filter: The typed KPI query filter carrying the story-attribute
            constraints.

    Returns:
        ``True`` when the row satisfies all active story-filter constraints.
    """
    sf = kpi_filter.story_filter
    if sf.story_type is not None and fact.story_type != sf.story_type:
        return False
    return not (sf.story_size is not None and fact.story_size != sf.story_size)


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
            Snapshot of all 40 registered KpiDefinition entries.
            ``catalog_status`` is ``COMPLETE`` — the full set is always returned.
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
        """Retrieve a named dashboard view by reading FactStore (AG3-038 / AG3-084).

        BC-16 §BC 16 Z. 1582: ``get_dashboard_view(project_key, view_kind)``.
        When FactStore is not configured, raises AnalyticsNotConfiguredError.

        Wires all five view kinds onto their respective ``fact_*`` read paths:

        - ``story`` — one row per completed story (``fact_story``, AG3-038).
        - ``guards`` — guard-period rollup rows (``fact_guard_period``, AG3-084).
        - ``pools`` — pool-period rollup rows (``fact_pool_period``, AG3-084).
        - ``pipeline`` — pipeline-period rollup rows (``fact_pipeline_period``, AG3-084).
        - ``corpus`` — corpus-period rollup rows (``fact_corpus_period``, AG3-084).

        Empty rollups yield ``DashboardViewStatus.EMPTY`` (HTTP 200, empty rows
        list) — never a silent empty or a ``StoryService`` fallback.
        FAIL-CLOSED: a missing fact table propagates the repository error.

        Period-rollup views (guards/pools/pipeline/corpus) require a
        ``PeriodFilter``; when none is supplied they raise ``ValueError``
        (fail-closed — avoids phantom EMPTY that bypasses a real FactStore read;
        use ``get_dashboard_view_with_filter`` for those dimensions).

        Args:
            project_key: Project scope.
            view_kind: One of ``story``, ``guards``, ``pools``, ``pipeline``,
                ``corpus``.

        Returns:
            DashboardView payload populated from FactStore.

        Raises:
            AnalyticsNotConfiguredError: When FactStore is not configured.
            ValueError: For unknown view_kind values (fail-closed) OR when
                guards/pools/pipeline/corpus is requested without a PeriodFilter
                (use ``get_dashboard_view_with_filter`` instead).
        """
        if self._fact_store is None:
            raise AnalyticsNotConfiguredError(
                "DashboardView requires FactStore; implemented in AG3-038+"
            )
        rows: list[DashboardFactRow]
        if view_kind == "story":
            rows = list(self._fact_store.list_fact_stories(project_key))
        elif view_kind in ("guards", "pools", "pipeline", "corpus"):
            # Period-grained dimensions require an explicit PeriodFilter.
            # Fail-closed: returning an empty list without a real FactStore read
            # would violate the invariant "EMPTY must ONLY reflect a real zero-row
            # FactStore read."  Force all callers to use get_dashboard_view_with_filter
            # for these dimensions.
            raise ValueError(
                f"Unfiltered dimension reads are not supported for "
                f"{view_kind!r}; use get_dashboard_view_with_filter with an "
                f"explicit KpiQueryFilter (period is required to avoid unbounded "
                f"cross-tenant full-table reads)."
            )
        else:
            raise ValueError(
                f"Unknown view_kind {view_kind!r}; accepted: "
                "story, guards, pools, pipeline, corpus"
            )
        status = DashboardViewStatus.EMPTY if not rows else DashboardViewStatus.OK
        return DashboardView(
            view_name=view_kind,
            project_key=project_key,
            status=status,
            rows=rows,
        )

    def get_dashboard_view_with_filter(
        self,
        project_key: str,
        view_kind: str,
        kpi_filter: KpiQueryFilter,
    ) -> DashboardView:
        """Retrieve a named dashboard view scoped by a typed KpiQueryFilter (AG3-084).

        Extends ``get_dashboard_view`` with explicit period-bounded fact reads for
        all five view kinds.  The ``kpi_filter.period`` is mandatory and forwarded
        to the FactStore as a ``PeriodFilter`` so reads are always project- and
        time-scoped.

        The reset/validity rule (FK-63 §63.3.1 / §63.4.1) is enforced upstream by
        the RefreshWorker purge chain (AG3-071/AG3-081/AG3-082): this method reads
        ONLY already-cleaned facts and performs NO late-query compensation for
        reset/corrupt-discarded runs.

        Args:
            project_key: Project scope.
            view_kind: One of ``story``, ``guards``, ``pools``, ``pipeline``,
                ``corpus``.
            kpi_filter: Typed KPI query filter (FK-63 §63.4.2); ``period`` bounds
                the fact read; entity/story filters narrow the result set.

        Returns:
            DashboardView with ``EMPTY`` status when rollups are genuinely empty.

        Raises:
            AnalyticsNotConfiguredError: When FactStore is not configured.
            ValueError: For unknown view_kind values (fail-closed).
        """
        if self._fact_store is None:
            raise AnalyticsNotConfiguredError(
                "DashboardView requires FactStore; implemented in AG3-038+"
            )
        from agentkit.kpi_analytics.fact_store.models import PeriodFilter

        period = PeriodFilter(start=kpi_filter.period.start, end=kpi_filter.period.end)
        sf = kpi_filter.story_filter

        # Fail-closed: story_filter attributes (story_type, story_size) are only
        # meaningful for the "story" dimension (fact_story table).  Requesting
        # story_type or story_size on a period-rollup dimension is a contradictory
        # filter that would silently discard user intent — reject it explicitly.
        if view_kind != "story" and (
            sf.story_type is not None or sf.story_size is not None
        ):
            raise ValueError(
                f"story_type / story_size filters are only supported for the 'story' "
                f"dimension (fact_story); dimension {view_kind!r} does not carry per-story "
                f"attributes. Remove the story_filter or use dimension='story'."
            )

        # Fail-closed: guard entity filter only applies to the "guards" dimension.
        if view_kind != "guards" and kpi_filter.entity_filter.guard is not None:
            raise ValueError(
                f"entity_filter.guard is only supported for dimension 'guards'; "
                f"dimension {view_kind!r} does not carry a guard_key column. "
                f"Remove the guard filter or use dimension='guards'."
            )

        # Fail-closed: pool entity filter only applies to the "pools" dimension.
        if view_kind != "pools" and kpi_filter.entity_filter.pool is not None:
            raise ValueError(
                f"entity_filter.pool is only supported for dimension 'pools'; "
                f"dimension {view_kind!r} does not carry a pool_key column. "
                f"Remove the pool filter or use dimension='pools'."
            )

        rows = _read_dimension_rows(
            self._fact_store, project_key, view_kind, period, kpi_filter
        )

        # AC5 comparison mode: perform a SECOND FactStore read using the comparison window.
        comparison_rows: list[DashboardFactRow] = []
        if kpi_filter.comparison_period is not None:
            comp_period = PeriodFilter(
                start=kpi_filter.comparison_period.start,
                end=kpi_filter.comparison_period.end,
            )
            comparison_rows = _read_dimension_rows(
                self._fact_store, project_key, view_kind, comp_period, kpi_filter
            )

        status = DashboardViewStatus.EMPTY if not rows else DashboardViewStatus.OK
        return DashboardView(
            view_name=view_kind,
            project_key=project_key,
            status=status,
            rows=rows,
            comparison_rows=comparison_rows,
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
