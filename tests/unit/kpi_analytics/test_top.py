"""Unit tests for KpiAnalytics top-level class.

AG3-029 Pass-3: signatures aligned to BC-16 §BC 16 Z. 1579 (W-A fix).
- refresh_analytics(project_key, hint_story_id=None) -> RefreshResult
- query(project_key, sql) -> KpiResult
- get_dashboard_view(project_key, view_kind) -> DashboardView
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.kpi_analytics.catalog import KpiCatalog, KpiCollectionPoint, KpiDefinition, KpiDomain, KpiGranularity
from agentkit.kpi_analytics.errors import AnalyticsNotConfiguredError
from agentkit.kpi_analytics.fact_store import FactStory, PeriodFilter
from agentkit.kpi_analytics.top import KpiAnalytics
from agentkit.kpi_analytics.views import DashboardViewStatus, RefreshStatus


class _DictFactStore:
    """Minimal FactStore double returning canned fact_story rows."""

    def __init__(self, stories: list[FactStory]) -> None:
        self._stories = stories

    def list_fact_stories(
        self, project_key: str, period: PeriodFilter | None = None
    ) -> list[FactStory]:
        return [s for s in self._stories if s.project_key == project_key]


def _make_catalog_with_one_kpi() -> KpiCatalog:
    catalog = KpiCatalog()
    catalog.register(
        KpiDefinition(
            kpi_id="qa_round_count",
            name="QA Round Count",
            decision_question="Are stories well-specified?",
            formula_repr="count(qa_rounds) per story",
            granularity=KpiGranularity.STORY,
            collection_point=KpiCollectionPoint(
                hook_or_event="story_closure_event",
                data_available=True,
            ),
            domain=KpiDomain.STORY_SIZING,
        )
    )
    return catalog


def test_list_kpis_returns_catalog_definitions() -> None:
    catalog = _make_catalog_with_one_kpi()
    analytics = KpiAnalytics(catalog=catalog)

    result = analytics.list_kpis()

    assert len(result) == 1
    assert result[0].kpi_id == "qa_round_count"


def test_list_kpis_returns_empty_for_empty_catalog() -> None:
    analytics = KpiAnalytics(catalog=KpiCatalog())

    result = analytics.list_kpis()

    assert result == []


def test_refresh_analytics_returns_skipped_when_no_fact_store() -> None:
    """BC-16: refresh_analytics(project_key, hint_story_id=None)."""
    analytics = KpiAnalytics(catalog=KpiCatalog())

    result = analytics.refresh_analytics("tenant-a")

    assert result.status == RefreshStatus.SKIPPED
    assert result.reason == "fact_store_or_refresh_worker_not_configured"
    assert result.refreshed_facts == 0
    assert result.errors == []


def test_refresh_analytics_returns_skipped_when_only_fact_store_provided() -> None:
    """Both fact_store AND refresh_worker must be present for a real refresh."""
    analytics = KpiAnalytics(catalog=KpiCatalog(), fact_store=object())

    result = analytics.refresh_analytics("tenant-a")

    assert result.status == RefreshStatus.SKIPPED


def test_refresh_analytics_with_hint_story_id_returns_skipped_when_no_infra() -> None:
    """BC-16: hint_story_id is an optional kwarg to refresh_analytics."""
    analytics = KpiAnalytics(catalog=KpiCatalog())

    result = analytics.refresh_analytics("tenant-a", hint_story_id="AG3-100")

    assert result.status == RefreshStatus.SKIPPED


def test_get_dashboard_view_raises_when_no_fact_store() -> None:
    """BC-16: get_dashboard_view(project_key, view_kind)."""
    analytics = KpiAnalytics(catalog=KpiCatalog())

    with pytest.raises(AnalyticsNotConfiguredError):
        analytics.get_dashboard_view("tenant-a", "board")


def test_get_dashboard_view_reads_factstore_story_rows() -> None:
    """AG3-038 AC7: get_dashboard_view reads real fact_story data."""
    story = FactStory(
        project_key="tenant-a",
        story_id="AG3-001",
        story_type="implementation",
        story_size="L",
        started_at=datetime(2026, 6, 5, tzinfo=UTC),
        qa_rounds=3,
        agentkit_version="3.19.0",
        agentkit_commit="abc",
    )
    analytics = KpiAnalytics(
        catalog=KpiCatalog(), fact_store=_DictFactStore([story])
    )

    view = analytics.get_dashboard_view("tenant-a", "story")

    assert view.status == DashboardViewStatus.OK
    assert len(view.rows) == 1
    assert view.rows[0]["story_id"] == "AG3-001"


def test_get_dashboard_view_empty_when_no_data() -> None:
    """AC7: an empty fact set yields an EMPTY view (status OK), not a stub error."""
    analytics = KpiAnalytics(catalog=KpiCatalog(), fact_store=_DictFactStore([]))

    view = analytics.get_dashboard_view("tenant-a", "story")

    assert view.status == DashboardViewStatus.OK
    assert view.rows == []


def test_get_dashboard_view_unwired_kind_fails_closed() -> None:
    """Period-rollup views are follow-up; requesting one fails closed, not empty."""
    analytics = KpiAnalytics(catalog=KpiCatalog(), fact_store=_DictFactStore([]))

    with pytest.raises(NotImplementedError):
        analytics.get_dashboard_view("tenant-a", "pipeline")


def test_query_raises_not_implemented() -> None:
    """BC-16: query(project_key, sql)."""
    analytics = KpiAnalytics(catalog=KpiCatalog())

    with pytest.raises(NotImplementedError):
        analytics.query("tenant-a", "SELECT * FROM kpi_story_metrics")


def test_get_design_tokens_raises_not_implemented() -> None:
    analytics = KpiAnalytics(catalog=KpiCatalog())

    with pytest.raises(NotImplementedError):
        analytics.get_design_tokens()
