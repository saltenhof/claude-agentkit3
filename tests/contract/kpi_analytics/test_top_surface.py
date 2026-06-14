"""Contract tests: pin the KpiAnalytics top-surface API.

These tests assert that the five public methods of KpiAnalytics have stable
signatures and docstrings. Any refactoring that breaks these tests breaks
the published contract of the kpi_analytics BC.

AG3-029 Pass-3: signatures aligned to BC-16 §BC 16 Z. 1579 (W-A fix).
- refresh_analytics(self, project_key, hint_story_id=None)
- get_dashboard_view(self, project_key, view_kind)
- query(self, project_key, sql)
"""

from __future__ import annotations

import inspect

import pytest

from agentkit.kpi_analytics.catalog import KpiCatalog
from agentkit.kpi_analytics.top import KpiAnalytics


@pytest.fixture()
def analytics() -> KpiAnalytics:
    return KpiAnalytics(catalog=KpiCatalog())


# ---------------------------------------------------------------------------
# Signature contracts (BC-16 §BC 16 Z. 1579 — authoritative)
# ---------------------------------------------------------------------------


def test_list_kpis_signature() -> None:
    sig = inspect.signature(KpiAnalytics.list_kpis)
    params = list(sig.parameters)
    assert params == ["self"]
    assert str(sig.return_annotation) in {"list[KpiDefinition]", "list[agentkit.kpi_analytics.catalog.KpiDefinition]"}


def test_refresh_analytics_signature() -> None:
    """BC-16 Z. 1581: refresh_analytics(project_key, hint_story_id=None)."""
    sig = inspect.signature(KpiAnalytics.refresh_analytics)
    params = list(sig.parameters)
    assert params == ["self", "project_key", "hint_story_id"]
    assert sig.parameters["hint_story_id"].default is None


def test_get_dashboard_view_signature() -> None:
    """BC-16 Z. 1582: get_dashboard_view(project_key, view_kind)."""
    sig = inspect.signature(KpiAnalytics.get_dashboard_view)
    params = list(sig.parameters)
    assert params == ["self", "project_key", "view_kind"]


def test_query_signature() -> None:
    """BC-16 Z. 1583: query(project_key, sql)."""
    sig = inspect.signature(KpiAnalytics.query)
    params = list(sig.parameters)
    assert params == ["self", "project_key", "sql"]


def test_get_design_tokens_signature() -> None:
    sig = inspect.signature(KpiAnalytics.get_design_tokens)
    params = list(sig.parameters)
    assert params == ["self"]


# ---------------------------------------------------------------------------
# Docstring contracts
# ---------------------------------------------------------------------------


def test_list_kpis_has_docstring() -> None:
    assert KpiAnalytics.list_kpis.__doc__ is not None
    assert len(KpiAnalytics.list_kpis.__doc__) > 0


def test_refresh_analytics_has_docstring() -> None:
    assert KpiAnalytics.refresh_analytics.__doc__ is not None
    assert len(KpiAnalytics.refresh_analytics.__doc__) > 0


def test_get_dashboard_view_has_docstring() -> None:
    assert KpiAnalytics.get_dashboard_view.__doc__ is not None
    assert len(KpiAnalytics.get_dashboard_view.__doc__) > 0


def test_query_has_docstring() -> None:
    assert KpiAnalytics.query.__doc__ is not None
    assert len(KpiAnalytics.query.__doc__) > 0


def test_get_design_tokens_has_docstring() -> None:
    assert KpiAnalytics.get_design_tokens.__doc__ is not None
    assert len(KpiAnalytics.get_design_tokens.__doc__) > 0


# ---------------------------------------------------------------------------
# Behavioural stubs are pinned as contract
# ---------------------------------------------------------------------------


def test_query_raises_not_implemented(analytics: KpiAnalytics) -> None:
    """BC-16: query(project_key, sql) stub raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        analytics.query("tenant-a", "SELECT * FROM kpi_story_metrics")


def test_get_design_tokens_returns_typed_token_set(analytics: KpiAnalytics) -> None:
    """AG3-092: get_design_tokens is real (no longer raises NotImplementedError)."""
    result = analytics.get_design_tokens()
    # Must be a DesignTokens with all families
    assert result.colors
    assert result.typography
    assert result.spacing
    assert result.control
    assert result.chart
