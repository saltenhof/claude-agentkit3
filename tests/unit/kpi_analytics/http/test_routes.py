"""Unit tests for kpi_analytics.http.routes (AG3-090, AC6).

Verifies:
  - GET /v1/projects/{key}/kpi/{dim} → 200 when kpi_analytics is configured.
  - KPI POST is read-only → always returns None.
  - GET → 503 kpi_unavailable when kpi_analytics is None (fail-closed).
  - Unrelated path → None.
  - Design-token route always available (no kpi_analytics dependency).
  - Period is mandatory → 400 when missing.
  - Naive datetimes rejected → 400.
  - Unknown params rejected → 400.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from agentkit.kpi_analytics.catalog import KpiCatalog
from agentkit.kpi_analytics.fact_store.store import FactStore
from agentkit.kpi_analytics.http.routes import KpiAnalyticsRoutes
from agentkit.kpi_analytics.top import KpiAnalytics

if TYPE_CHECKING:
    from agentkit.kpi_analytics.fact_store.models import FactStory, PeriodFilter

_CORR = "test-corr-kpi-001"
_KPI_DIMENSIONS = ("stories", "guards", "pools", "pipeline", "corpus")
_PERIOD_QUERY_DICT: dict[str, list[str]] = {
    "from": ["2026-01-01T00:00:00Z"],
    "to": ["2026-12-31T00:00:00Z"],
}


class _EmptyFactRepo:
    """Minimal in-memory FactRepository returning empty lists for all dimensions."""

    def list_fact_stories(
        self, project_key: str, period: PeriodFilter | None = None
    ) -> list[FactStory]:
        return []

    def list_fact_guards(self, project_key: str, period: PeriodFilter) -> list:
        return []

    def list_fact_pool(self, project_key: str, period: PeriodFilter) -> list:
        return []

    def list_fact_pipeline(self, project_key: str, period: PeriodFilter) -> list:
        return []

    def list_fact_corpus(self, project_key: str, period: PeriodFilter) -> list:
        return []

    def get_sync_state(self, project_key: str, key: str) -> None:
        return None

    def upsert_fact_story(self, fact: object) -> None: ...
    def upsert_fact_guard(self, fact: object) -> None: ...
    def upsert_fact_pool(self, fact: object) -> None: ...
    def upsert_fact_pipeline(self, fact: object) -> None: ...
    def upsert_fact_corpus(self, fact: object) -> None: ...
    def upsert_sync_state(self, fact: object) -> None: ...

    def begin_write_session(self) -> object:
        raise NotImplementedError


def _make_analytics() -> KpiAnalytics:
    """Build a minimal KpiAnalytics with an empty in-memory FactStore."""
    return KpiAnalytics(
        catalog=KpiCatalog(), fact_store=FactStore(_EmptyFactRepo())
    )


def _json(response: object) -> object:
    from agentkit.control_plane.models import BcRouteResponse

    assert isinstance(response, BcRouteResponse)
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# KPI dimension endpoints — require kpi_analytics to return 200
# ---------------------------------------------------------------------------


def test_get_kpi_root_with_analytics_returns_200() -> None:
    routes = KpiAnalyticsRoutes(kpi_analytics=_make_analytics())
    result = routes.handle_get("/v1/projects/myproj/kpi", _PERIOD_QUERY_DICT, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["project_key"] == "myproj"


@pytest.mark.parametrize("dimension", _KPI_DIMENSIONS)
def test_get_kpi_dimension_with_analytics_returns_200(dimension: str) -> None:
    """PO decision 2026-06-08: singular /kpi root with 5 dimension sub-routes."""
    routes = KpiAnalyticsRoutes(kpi_analytics=_make_analytics())
    result = routes.handle_get(
        f"/v1/projects/myproj/kpi/{dimension}", _PERIOD_QUERY_DICT, _CORR
    )
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["dimension"] == dimension


def test_kpi_post_is_readonly_returns_none() -> None:
    """KPI surface is read-only; POST must return None (not claimed)."""
    routes = KpiAnalyticsRoutes(kpi_analytics=_make_analytics())
    assert routes.handle_post("/v1/projects/myproj/kpi", {}, _CORR) is None
    assert routes.handle_post("/v1/projects/myproj/kpi/stories", {}, _CORR) is None


# ---------------------------------------------------------------------------
# Fail-closed: 503 when kpi_analytics is None
# ---------------------------------------------------------------------------


def test_get_kpi_unavailable_returns_503() -> None:
    """Fail-closed: no kpi_analytics configured → 503 kpi_unavailable."""
    routes = KpiAnalyticsRoutes()  # kpi_analytics=None
    result = routes.handle_get("/v1/projects/myproj/kpi", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "kpi_unavailable"


@pytest.mark.parametrize("dimension", _KPI_DIMENSIONS)
def test_get_kpi_dimension_unavailable_returns_503(dimension: str) -> None:
    """Fail-closed: each dimension returns 503 when kpi_analytics is None."""
    routes = KpiAnalyticsRoutes()
    result = routes.handle_get(
        f"/v1/projects/myproj/kpi/{dimension}", _PERIOD_QUERY_DICT, _CORR
    )
    assert result is not None
    assert result.status_code == int(HTTPStatus.SERVICE_UNAVAILABLE)


# ---------------------------------------------------------------------------
# Path routing
# ---------------------------------------------------------------------------


def test_unknown_kpi_dimension_returns_none() -> None:
    """Dimension not in the allow-list must not be claimed by this route."""
    routes = KpiAnalyticsRoutes(kpi_analytics=_make_analytics())
    assert (
        routes.handle_get("/v1/projects/myproj/kpi/unknown-dim", {}, _CORR) is None
    )


def test_unrelated_path_returns_none() -> None:
    routes = KpiAnalyticsRoutes(kpi_analytics=_make_analytics())
    assert routes.handle_get("/v1/projects/myproj/phases", {}, _CORR) is None


# ---------------------------------------------------------------------------
# Period validation (fail-closed)
# ---------------------------------------------------------------------------


def test_missing_period_returns_400() -> None:
    """Period is mandatory — missing from/to → 400 invalid_kpi_filter."""
    routes = KpiAnalyticsRoutes(kpi_analytics=_make_analytics())
    result = routes.handle_get("/v1/projects/myproj/kpi/stories", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.BAD_REQUEST)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "invalid_kpi_filter"


def test_naive_datetime_returns_400() -> None:
    """Naive (timezone-unaware) timestamps are rejected with 400."""
    routes = KpiAnalyticsRoutes(kpi_analytics=_make_analytics())
    result = routes.handle_get(
        "/v1/projects/myproj/kpi/stories",
        {"from": ["2026-01-01T00:00:00"], "to": ["2026-12-31T00:00:00"]},
        _CORR,
    )
    assert result is not None
    assert result.status_code == int(HTTPStatus.BAD_REQUEST)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "invalid_kpi_filter"


def test_unknown_query_param_returns_400() -> None:
    """Unknown query parameters are rejected with 400 invalid_kpi_filter."""
    routes = KpiAnalyticsRoutes(kpi_analytics=_make_analytics())
    result = routes.handle_get(
        "/v1/projects/myproj/kpi/stories",
        {**_PERIOD_QUERY_DICT, "evil_param": ["x"]},
        _CORR,
    )
    assert result is not None
    assert result.status_code == int(HTTPStatus.BAD_REQUEST)


# ---------------------------------------------------------------------------
# Finding #6: project_key in query string is always rejected
# ---------------------------------------------------------------------------


def test_project_key_matching_path_in_query_string_returns_400() -> None:
    """Finding #6: project_key in query string is redundant → 400 (path is authoritative)."""
    routes = KpiAnalyticsRoutes(kpi_analytics=_make_analytics())
    result = routes.handle_get(
        "/v1/projects/myproj/kpi/stories",
        {**_PERIOD_QUERY_DICT, "project_key": ["myproj"]},
        _CORR,
    )
    assert result is not None
    assert result.status_code == int(HTTPStatus.BAD_REQUEST)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "invalid_kpi_filter"


def test_project_key_mismatching_path_in_query_string_returns_400() -> None:
    """Finding #6: project_key mismatch in query string → 400."""
    routes = KpiAnalyticsRoutes(kpi_analytics=_make_analytics())
    result = routes.handle_get(
        "/v1/projects/myproj/kpi/stories",
        {**_PERIOD_QUERY_DICT, "project_key": ["other-tenant"]},
        _CORR,
    )
    assert result is not None
    assert result.status_code == int(HTTPStatus.BAD_REQUEST)
    body = _json(result)
    assert isinstance(body, dict)
    assert body["error_code"] == "invalid_kpi_filter"


# ---------------------------------------------------------------------------
# AG3-092 — design token route tests (AC3)
# ---------------------------------------------------------------------------


def test_design_tokens_route_returns_200() -> None:
    """AC3: GET /v1/projects/{key}/kpi/design-tokens returns 200."""
    routes = KpiAnalyticsRoutes()  # design-tokens are always available
    result = routes.handle_get("/v1/projects/myproj/kpi/design-tokens", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)


def test_design_tokens_route_available_even_when_kpi_analytics_none() -> None:
    """AC3: design-token endpoint is always available (no backend dependency)."""
    routes = KpiAnalyticsRoutes()  # kpi_analytics=None
    result = routes.handle_get("/v1/projects/myproj/kpi/design-tokens", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)


def test_design_tokens_route_echoes_project_key() -> None:
    """AC3: response includes the project_key from the path."""
    routes = KpiAnalyticsRoutes()
    result = routes.handle_get("/v1/projects/tenant-x/kpi/design-tokens", {}, _CORR)
    assert result is not None
    body = _json(result)
    assert isinstance(body, dict)
    assert body["project_key"] == "tenant-x"


def test_design_tokens_route_contains_all_families() -> None:
    """AC3: response body contains all token families."""
    routes = KpiAnalyticsRoutes()
    result = routes.handle_get("/v1/projects/myproj/kpi/design-tokens", {}, _CORR)
    assert result is not None
    body = _json(result)
    assert isinstance(body, dict)
    assert "colors" in body
    assert "typography" in body
    assert "spacing" in body
    assert "control" in body
    assert "chart" in body


def test_design_tokens_route_body_is_deterministic() -> None:
    """AC3: two calls return identical bodies (deterministic token set)."""
    routes = KpiAnalyticsRoutes()
    r1 = routes.handle_get("/v1/projects/myproj/kpi/design-tokens", {}, _CORR)
    r2 = routes.handle_get("/v1/projects/myproj/kpi/design-tokens", {}, _CORR)
    assert r1 is not None
    assert r2 is not None
    assert r1.body == r2.body


def test_design_tokens_route_not_claimed_by_dimension_handler() -> None:
    """AC3: design-tokens sub-path is NOT matched by the dimension handler."""
    routes = KpiAnalyticsRoutes()
    result = routes.handle_get("/v1/projects/myproj/kpi/design-tokens", {}, _CORR)
    assert result is not None
    assert result.status_code == int(HTTPStatus.OK)
