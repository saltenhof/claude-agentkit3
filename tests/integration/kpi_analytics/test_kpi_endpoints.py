"""Integration tests for the five KPI read endpoints (AG3-084).

Tests the real ControlPlaneApplication wiring with KpiAnalyticsRoutes backed
by an in-memory FactRepository (with period-aware filtering).  Covers:

- AC1: five endpoints respond at /v1/projects/{key}/kpi/{dim}.
- AC2: project_key is mandatory; missing/ambiguous → fail-closed.
- AC3: endpoints read FactStore, not StoryService.
- AC4: all five view kinds (story/guards/pools/pipeline/corpus) respond (no 501).
- AC5: KpiQueryFilter validation; invalid filter → 400; comparison mode works.
- AC6: reset rule — reset rows absent; no late-query fix.
- AC7: EMPTY → HTTP 200 with status=EMPTY, rows=[].
- AC8: no /api/live/stories endpoint exists (test confirms 503/404).

All tests dispatch through the REAL ControlPlaneApplication so that tenant-scope
middleware, path-regex matching, and BC-route wiring are all exercised end-to-end.
A non-wired KpiAnalytics (``kpi_analytics=None``) causes these tests to fail with
503, proving that the production wiring is exercised (finding #12 fix).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from agentkit.control_plane.http import ControlPlaneApplication
from agentkit.control_plane_http.app import ControlPlaneApplicationRoutes
from agentkit.control_plane_http.tenant_scope import TenantScopeMiddleware
from agentkit.kpi_analytics.catalog import KpiCatalog
from agentkit.kpi_analytics.fact_store.models import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStory,
    PeriodFilter,
)
from agentkit.kpi_analytics.fact_store.store import FactStore
from agentkit.kpi_analytics.http.routes import KpiAnalyticsRoutes
from agentkit.kpi_analytics.top import KpiAnalytics
from agentkit.project_management.entities import ProjectConfiguration
from agentkit.project_management.lifecycle import create_project
from agentkit.state_backend.store import facade
from agentkit.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)

_CORR = "test-corr-ag3-084"
_PROJECT = "tenant-a"
_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_END = datetime(2026, 12, 31, tzinfo=UTC)
# Use Z-suffix ISO format.
_FROM = "2026-01-01T00:00:00Z"
_TO = "2026-12-31T00:00:00Z"
_PERIOD_QUERY = f"from={_FROM}&to={_TO}"


# ---------------------------------------------------------------------------
# Fixtures: reset backend cache + seed project for tenant-scope middleware
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_backend(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin SQLite for all tests in this module (Docker-free)."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    facade.reset_backend_cache_for_tests()
    yield
    facade.reset_backend_cache_for_tests()


# ---------------------------------------------------------------------------
# In-memory FactRepository that HONOURS period predicates (finding #14 fix)
# ---------------------------------------------------------------------------


class _InMemoryFactRepo:
    """Minimal in-memory FactRepository for integration tests (no SQLite required).

    Period filtering is enforced so that period behaviour is proven end-to-end:
    - ``list_fact_stories``: filters by ``completed_at`` in ``[period.start, period.end)``.
    - ``list_fact_guards/pool/pipeline/corpus``: filter by ``period_start`` in range.
    """

    def __init__(
        self,
        *,
        stories: list[FactStory] | None = None,
        guards: list[FactGuardPeriod] | None = None,
        pools: list[FactPoolPeriod] | None = None,
        pipeline: list[FactPipelinePeriod] | None = None,
        corpus: list[FactCorpusPeriod] | None = None,
    ) -> None:
        self._stories = stories or []
        self._guards = guards or []
        self._pools = pools or []
        self._pipeline = pipeline or []
        self._corpus = corpus or []

    def list_fact_stories(
        self, project_key: str, period: PeriodFilter | None = None
    ) -> list[FactStory]:
        rows = [s for s in self._stories if s.project_key == project_key]
        if period is not None:
            rows = [
                s
                for s in rows
                if s.completed_at is not None
                and period.start <= s.completed_at < period.end
            ]
        return rows

    def list_fact_guards(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactGuardPeriod]:
        return [
            g
            for g in self._guards
            if g.project_key == project_key
            and period.start <= g.period_start < period.end
        ]

    def list_fact_pool(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactPoolPeriod]:
        return [
            p
            for p in self._pools
            if p.project_key == project_key
            and period.start <= p.period_start < period.end
        ]

    def list_fact_pipeline(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactPipelinePeriod]:
        return [
            p
            for p in self._pipeline
            if p.project_key == project_key
            and period.start <= p.period_start < period.end
        ]

    def list_fact_corpus(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactCorpusPeriod]:
        return [
            c
            for c in self._corpus
            if c.project_key == project_key
            and period.start <= c.period_start < period.end
        ]

    # Write methods (not exercised in read-only tests but required by Protocol).
    def get_sync_state(self, project_key: str, key: str) -> None:
        return None

    def upsert_fact_story(self, fact: FactStory) -> None: ...
    def upsert_fact_guard(self, fact: FactGuardPeriod) -> None: ...
    def upsert_fact_pool(self, fact: FactPoolPeriod) -> None: ...
    def upsert_fact_pipeline(self, fact: FactPipelinePeriod) -> None: ...
    def upsert_fact_corpus(self, fact: FactCorpusPeriod) -> None: ...
    def upsert_sync_state(self, fact: object) -> None: ...

    def begin_write_session(self) -> object:
        raise NotImplementedError("write sessions not supported in test double")


# ---------------------------------------------------------------------------
# Application factory — dispatches through REAL ControlPlaneApplication
# ---------------------------------------------------------------------------


def _make_kpi_analytics(
    *,
    stories: list[FactStory] | None = None,
    guards: list[FactGuardPeriod] | None = None,
    pools: list[FactPoolPeriod] | None = None,
    pipeline: list[FactPipelinePeriod] | None = None,
    corpus: list[FactCorpusPeriod] | None = None,
) -> KpiAnalytics:
    repo = _InMemoryFactRepo(
        stories=stories,
        guards=guards,
        pools=pools,
        pipeline=pipeline,
        corpus=corpus,
    )
    fact_store = FactStore(repo)
    return KpiAnalytics(catalog=KpiCatalog(), fact_store=fact_store)


def _make_app(
    tmp_path: object,
    analytics: KpiAnalytics | None = None,
    *,
    seed_project: bool = True,
) -> ControlPlaneApplication:
    """Build a real ControlPlaneApplication wired with the given KpiAnalytics.

    Uses a real SQLite-backed ProjectRepository for TenantScopeMiddleware so
    that tenant-scope middleware resolves project existence correctly.  All
    other BC routes use their no-op defaults (they are not under test here).

    If ``analytics`` is None the KpiAnalyticsRoutes are built without a
    KpiAnalytics, so the endpoints return 503 — this proves that a non-wired
    production app causes test failures (finding #12 validation).

    Args:
        tmp_path: pytest tmp_path fixture value for the SQLite db directory.
        analytics: Optional KpiAnalytics to wire.
        seed_project: When True, seed "tenant-a" so TenantScopeMiddleware
            accepts requests for that project_key.
    """
    from pathlib import Path

    store_dir = Path(str(tmp_path))  # type: ignore[arg-type]
    project_repo = StateBackendProjectRepository(store_dir)

    if seed_project:
        config = ProjectConfiguration(
            repo_url="",
            default_branch="main",
            default_worker_count=2,
            repositories=["repo-a"],
        )
        project_repo.save(
            create_project(
                "tenant-a", "Tenant A", "AG3", config, repositories=["repo-a"]
            )
        )

    tenant_scope = TenantScopeMiddleware(repository=project_repo)
    kpi_routes = KpiAnalyticsRoutes(kpi_analytics=analytics)

    return ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(
            kpi_analytics_routes=kpi_routes,
        ),
        tenant_scope_middleware=tenant_scope,
    )


def _get(
    app: ControlPlaneApplication,
    path: str,
    query_str: str = "",
) -> tuple[int, object]:
    """Dispatch a GET request through the real ControlPlaneApplication."""
    full_path = f"{path}?{query_str}" if query_str else path
    response = app.handle_request(
        method="GET",
        path=full_path,
        body=b"",
        request_headers={"X-Correlation-Id": _CORR},
    )
    body = json.loads(response.body.decode("utf-8"))
    return response.status_code, body


# ---------------------------------------------------------------------------
# Proof: non-wired app returns 503 (validates production-wiring coverage)
# ---------------------------------------------------------------------------


def test_unwired_app_returns_503_not_200(tmp_path: object) -> None:
    """Finding #12 proof: non-wired KpiAnalyticsRoutes returns 503, not 200.

    This test would PASS with the old KpiAnalyticsRoutes() stub (which returned
    200 from service_available=True), but it must FAIL until finding #2 is fixed.
    After fixing, a properly wired app returns 200; an unwired app returns 503.
    """
    # Build an app with kpi_analytics=None (simulates a broken composition root).
    app = _make_app(tmp_path, analytics=None)
    status, body = _get(app, f"/v1/projects/{_PROJECT}/kpi/stories", _PERIOD_QUERY)
    # Must be 503 — not a fake 200 from a legacy compat stub.
    assert status == 503
    assert body["error_code"] == "kpi_unavailable"


# ---------------------------------------------------------------------------
# AC1: five endpoints exist and respond (real app dispatch)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dimension", ["stories", "guards", "pools", "pipeline", "corpus"])
def test_kpi_dimension_endpoint_exists(tmp_path: object, dimension: str) -> None:
    """AC1: GET /v1/projects/{key}/kpi/{dim} responds (not 404, not 501, not 503)."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/{dimension}"
    status, body = _get(app, path, _PERIOD_QUERY)

    assert status == 200, f"Expected 200, got {status}: {body}"
    assert body["project_key"] == _PROJECT
    assert body["dimension"] == dimension


def test_kpi_root_endpoint_exists(tmp_path: object) -> None:
    """AC1: GET /v1/projects/{key}/kpi (root, no dimension) also responds."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi"
    status, _body = _get(app, path, _PERIOD_QUERY)

    assert status == 200


# ---------------------------------------------------------------------------
# AC7: empty rollups → HTTP 200 EMPTY
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dimension", ["stories", "guards", "pools", "pipeline", "corpus"])
def test_empty_rollup_returns_200_with_empty_status(
    tmp_path: object, dimension: str
) -> None:
    """AC7: empty FactStore → HTTP 200, status=EMPTY, rows=[]."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/{dimension}"
    status, body = _get(app, path, _PERIOD_QUERY)

    assert status == 200
    assert body["status"] == "EMPTY"
    assert body["rows"] == []


# ---------------------------------------------------------------------------
# AC1 + AC4: non-empty data comes back for stories dimension
# ---------------------------------------------------------------------------


def test_stories_endpoint_with_data_returns_ok_status(tmp_path: object) -> None:
    """AC1 + AC4: stories endpoint with data returns status=OK, rows=[{...}]."""
    story = FactStory(
        project_key=_PROJECT,
        story_id="AG3-101",
        story_type="implementation",
        story_size="M",
        started_at=_NOW,
        completed_at=datetime(2026, 3, 1, tzinfo=UTC),
        qa_rounds=2,
        agentkit_version="3.0.0",
        agentkit_commit="abc",
    )
    analytics = _make_kpi_analytics(stories=[story])
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/stories"
    status, body = _get(app, path, _PERIOD_QUERY)

    assert status == 200
    assert body["status"] == "OK"
    assert len(body["rows"]) == 1
    assert body["rows"][0]["story_id"] == "AG3-101"


# ---------------------------------------------------------------------------
# AC4: period-grained dimensions (guards/pools/pipeline/corpus) with data
# ---------------------------------------------------------------------------


def test_guards_endpoint_with_data_returns_ok_status(tmp_path: object) -> None:
    """AC4: guards endpoint with matching-period data returns status=OK."""
    guard = FactGuardPeriod(
        project_key=_PROJECT,
        guard_id="review-guard",
        period_start=datetime(2026, 3, 1, tzinfo=UTC),
        period_end=datetime(2026, 4, 1, tzinfo=UTC),
        invocation_count=5,
        violation_count=1,
    )
    analytics = _make_kpi_analytics(guards=[guard])
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/guards"
    status, body = _get(app, path, _PERIOD_QUERY)

    assert status == 200
    assert body["status"] == "OK"
    assert len(body["rows"]) == 1
    assert body["rows"][0]["guard_id"] == "review-guard"


def test_guards_outside_period_returns_empty(tmp_path: object) -> None:
    """AC4 + period filtering: guard outside the query period returns EMPTY.

    Proves the _InMemoryFactRepo honours period predicates (finding #14 fix).
    """
    # Guard period_start is 2025-06-01, but the query period is 2026.
    guard = FactGuardPeriod(
        project_key=_PROJECT,
        guard_id="old-guard",
        period_start=datetime(2025, 6, 1, tzinfo=UTC),
        period_end=datetime(2025, 7, 1, tzinfo=UTC),
        invocation_count=3,
        violation_count=0,
    )
    analytics = _make_kpi_analytics(guards=[guard])
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/guards"
    status, body = _get(app, path, _PERIOD_QUERY)  # 2026-01-01..2026-12-31

    assert status == 200
    assert body["status"] == "EMPTY"
    assert body["rows"] == []


def test_pools_endpoint_with_data_returns_ok_status(tmp_path: object) -> None:
    """AC4: pools endpoint with matching-period data returns status=OK."""
    pool = FactPoolPeriod(
        project_key=_PROJECT,
        llm_role="primary",
        period_start=datetime(2026, 3, 1, tzinfo=UTC),
        period_end=datetime(2026, 4, 1, tzinfo=UTC),
        call_count=100,
        token_input_total=50000,
        token_output_total=20000,
    )
    analytics = _make_kpi_analytics(pools=[pool])
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/pools"
    status, body = _get(app, path, _PERIOD_QUERY)

    assert status == 200
    assert body["status"] == "OK"
    assert len(body["rows"]) == 1


def test_pipeline_endpoint_with_data_returns_ok_status(tmp_path: object) -> None:
    """AC4: pipeline endpoint with matching-period data returns status=OK."""
    pipeline = FactPipelinePeriod(
        project_key=_PROJECT,
        period_start=datetime(2026, 3, 1, tzinfo=UTC),
        period_end=datetime(2026, 4, 1, tzinfo=UTC),
        stories_completed=10,
        stories_escalated=1,
    )
    analytics = _make_kpi_analytics(pipeline=[pipeline])
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/pipeline"
    status, body = _get(app, path, _PERIOD_QUERY)

    assert status == 200
    assert body["status"] == "OK"


def test_corpus_endpoint_with_data_returns_ok_status(tmp_path: object) -> None:
    """AC4: corpus endpoint with matching-period data returns status=OK."""
    corpus = FactCorpusPeriod(
        project_key=_PROJECT,
        period_start=datetime(2026, 3, 1, tzinfo=UTC),
        period_end=datetime(2026, 4, 1, tzinfo=UTC),
        incidents_recorded=3,
        patterns_promoted=1,
        checks_approved=5,
    )
    analytics = _make_kpi_analytics(corpus=[corpus])
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/corpus"
    status, body = _get(app, path, _PERIOD_QUERY)

    assert status == 200
    assert body["status"] == "OK"


# ---------------------------------------------------------------------------
# AC2: project_key mandatory — unknown project returns middleware error
# ---------------------------------------------------------------------------


def test_kpi_unknown_project_returns_error(tmp_path: object) -> None:
    """AC2: unknown project_key → tenant-scope middleware rejects (404/403)."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics, seed_project=True)

    # "unknown-project" was not seeded — middleware should reject it.
    status, _body = _get(
        app, "/v1/projects/unknown-project/kpi/stories", _PERIOD_QUERY
    )
    # Middleware returns 404 (project not found) or 403 (forbidden).
    assert status in (403, 404), f"Expected 403/404, got {status}"


def test_kpi_route_unknown_dimension_not_claimed(tmp_path: object) -> None:
    """AC2: unknown dimension not in allow-list → not claimed (404)."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    # "live" is not a registered KPI dimension; route won't be claimed.
    status, _body = _get(app, f"/v1/projects/{_PROJECT}/kpi/live", _PERIOD_QUERY)
    assert status == 404, f"Expected 404, got {status}"


# ---------------------------------------------------------------------------
# AC5: KpiQueryFilter validation — invalid filter → 400
# ---------------------------------------------------------------------------


def test_reversed_period_returns_400(tmp_path: object) -> None:
    """AC5: from > to (reversed period) → 400 invalid_kpi_filter."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/stories"
    bad_query = "from=2026-12-31T00:00:00Z&to=2026-01-01T00:00:00Z"
    status, body = _get(app, path, bad_query)

    assert status == 400
    assert body["error_code"] == "invalid_kpi_filter"


def test_guard_and_pool_both_set_returns_400(tmp_path: object) -> None:
    """AC5: guard + pool both set → 400 (mutually exclusive entity filter)."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/stories"
    bad_query = f"{_PERIOD_QUERY}&guard=g1&pool=p1"
    status, body = _get(app, path, bad_query)

    assert status == 400
    assert body["error_code"] == "invalid_kpi_filter"


def test_missing_period_returns_400(tmp_path: object) -> None:
    """AC5 + finding #4: missing period → 400 invalid_kpi_filter.

    Period is MANDATORY (FK-63 §63.3.3): no unbounded full-table scan allowed.
    EMPTY 200 without a period would bypass the fail-closed contract — rejected
    with 400 instead.
    """
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/stories"
    status, body = _get(app, path, "")  # no from/to

    assert status == 400
    assert body["error_code"] == "invalid_kpi_filter"


def test_naive_timestamp_returns_400(tmp_path: object) -> None:
    """Finding #7: naive datetimes (no tz) are rejected with 400."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/stories"
    # Naive ISO timestamp — no Z and no offset.
    naive_query = "from=2026-01-01T00:00:00&to=2026-12-31T00:00:00"
    status, body = _get(app, path, naive_query)

    assert status == 400
    assert body["error_code"] == "invalid_kpi_filter"


def test_unknown_query_param_returns_400(tmp_path: object) -> None:
    """Finding #8: unknown query parameters are rejected with 400."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/stories"
    bad_query = f"{_PERIOD_QUERY}&unknown_param=foo"
    status, body = _get(app, path, bad_query)

    assert status == 400
    assert body["error_code"] == "invalid_kpi_filter"


def test_unsupported_story_filter_on_guards_returns_400(tmp_path: object) -> None:
    """Finding #9: story_type filter on guards dimension → 400 (fail-closed)."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/guards"
    bad_query = f"{_PERIOD_QUERY}&story_type=implementation"
    status, body = _get(app, path, bad_query)

    assert status == 400
    assert body["error_code"] == "invalid_kpi_view_kind"


def test_unsupported_guard_filter_on_corpus_returns_400(tmp_path: object) -> None:
    """Finding #9: guard entity filter on corpus dimension → 400 (fail-closed)."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/corpus"
    bad_query = f"{_PERIOD_QUERY}&guard=my-guard"
    status, body = _get(app, path, bad_query)

    assert status == 400
    assert body["error_code"] == "invalid_kpi_view_kind"


# ---------------------------------------------------------------------------
# AC5: comparison mode (compare_from / compare_to) — finding #5
# ---------------------------------------------------------------------------


def test_comparison_period_parsed_and_surfaced(tmp_path: object) -> None:
    """AC5: compare_from/compare_to are parsed and surfaced in response."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/stories"
    compare_query = (
        f"{_PERIOD_QUERY}"
        "&compare_from=2025-01-01T00:00:00Z"
        "&compare_to=2025-12-31T00:00:00Z"
    )
    status, body = _get(app, path, compare_query)

    assert status == 200
    assert "comparison_period" in body
    assert body["comparison_period"]["from"] == "2025-01-01T00:00:00+00:00"


def test_partial_comparison_period_returns_400(tmp_path: object) -> None:
    """AC5: only compare_from without compare_to → 400."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/stories"
    bad_query = f"{_PERIOD_QUERY}&compare_from=2025-01-01T00:00:00Z"
    status, body = _get(app, path, bad_query)

    assert status == 400
    assert body["error_code"] == "invalid_kpi_filter"


def test_comparison_period_overlapping_main_period_returns_400(
    tmp_path: object,
) -> None:
    """AC5: comparison_period.end > period.start → 400 (KpiQueryFilter validates)."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/stories"
    # compare_to=2026-06-01 is AFTER period.start=2026-01-01 → invalid
    bad_query = (
        f"{_PERIOD_QUERY}"
        "&compare_from=2025-01-01T00:00:00Z"
        "&compare_to=2026-06-01T00:00:00Z"
    )
    status, body = _get(app, path, bad_query)

    assert status == 400
    assert body["error_code"] == "invalid_kpi_filter"


# ---------------------------------------------------------------------------
# AC8: no /api/live/stories endpoint (FAIL-CLOSED — not even a stub)
# ---------------------------------------------------------------------------


def test_no_live_stories_endpoint(tmp_path: object) -> None:
    """AC8: /api/live/stories is NOT served (returns 404 from the real app)."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    status, _body = _get(app, "/api/live/stories")
    # The real app returns 404 for unregistered paths.
    assert status == 404, f"No live endpoint must exist; got {status}"


def test_no_v1_live_stories_endpoint(tmp_path: object) -> None:
    """AC8: /v1/projects/{key}/live/stories also NOT served (404)."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    status, _body = _get(app, f"/v1/projects/{_PROJECT}/live/stories")
    assert status in (403, 404), f"No live endpoint must exist; got {status}"


# ---------------------------------------------------------------------------
# Cross-project isolation: project_key scoped
# ---------------------------------------------------------------------------


def test_kpi_stories_scoped_to_project_key(tmp_path: object) -> None:
    """AC2: KPI reads are scoped by project_key (tenant-a ≠ tenant-b)."""
    from pathlib import Path

    from agentkit.state_backend.store.project_management_repository import (
        StateBackendProjectRepository,
    )

    # Seed both tenant-a and tenant-b.
    store_dir = Path(str(tmp_path))  # type: ignore[arg-type]
    project_repo = StateBackendProjectRepository(store_dir)
    for key, name, prefix, repo in [
        ("tenant-a", "Tenant A", "AG3", "repo-a"),
        ("tenant-b", "Tenant B", "TB", "repo-b"),
    ]:
        config = ProjectConfiguration(
            repo_url="", default_branch="main", default_worker_count=1, repositories=[repo]
        )
        project_repo.save(create_project(key, name, prefix, config, repositories=[repo]))

    story_a = FactStory(
        project_key="tenant-a",
        story_id="A-001",
        story_type="implementation",
        story_size="S",
        started_at=_NOW,
        completed_at=datetime(2026, 3, 1, tzinfo=UTC),
        qa_rounds=1,
        agentkit_version="3.0.0",
        agentkit_commit="abc",
    )
    story_b = FactStory(
        project_key="tenant-b",
        story_id="B-001",
        story_type="bugfix",
        story_size="XS",
        started_at=_NOW,
        completed_at=datetime(2026, 3, 1, tzinfo=UTC),
        qa_rounds=1,
        agentkit_version="3.0.0",
        agentkit_commit="def",
    )
    analytics = _make_kpi_analytics(stories=[story_a, story_b])
    tenant_scope = TenantScopeMiddleware(repository=project_repo)
    kpi_routes = KpiAnalyticsRoutes(kpi_analytics=analytics)
    app = ControlPlaneApplication(
        routes=ControlPlaneApplicationRoutes(kpi_analytics_routes=kpi_routes),
        tenant_scope_middleware=tenant_scope,
    )

    status_a, body_a = _get(app, "/v1/projects/tenant-a/kpi/stories", _PERIOD_QUERY)
    status_b, body_b = _get(app, "/v1/projects/tenant-b/kpi/stories", _PERIOD_QUERY)

    assert status_a == 200
    a_ids = [r["story_id"] for r in body_a["rows"]]
    assert "A-001" in a_ids
    assert "B-001" not in a_ids  # cross-project leak must not occur

    assert status_b == 200
    b_ids = [r["story_id"] for r in body_b["rows"]]
    assert "B-001" in b_ids
    assert "A-001" not in b_ids  # cross-project leak must not occur


# ---------------------------------------------------------------------------
# AC3: KPI endpoints read FactStore NOT StoryService
# ---------------------------------------------------------------------------


def test_kpi_routes_do_not_access_story_service() -> None:
    """AC3: KpiAnalyticsRoutes uses KpiAnalytics (FactStore); StoryService not in path."""
    import inspect

    from agentkit.kpi_analytics.http import routes as routes_module

    source = inspect.getsource(routes_module)
    assert "StoryService" not in source, (
        "KpiAnalyticsRoutes must NOT reference StoryService (DRIFT-AG3-038 fix)"
    )


# ---------------------------------------------------------------------------
# AC6: reset rule — purged runs do not appear (no late-query compensation)
# ---------------------------------------------------------------------------


def test_reset_story_purged_upstream_is_absent_from_kpi(tmp_path: object) -> None:
    """AC6 (Finding #4): upstream purge removes reset story; KPI read must not re-introduce it.

    Phase 1 — before purge: BOTH clean and reset stories are present in the repo.
    Phase 2 — after purge: only the clean story remains (upstream AG3-071/082 deleted RESET-002).
    The KPI read path must:
    - Return both stories when both are present (phase 1).
    - Return ONLY the clean story after the purge (phase 2).
    - NOT try to re-fetch from any second source.
    """
    clean_story = FactStory(
        project_key=_PROJECT,
        story_id="CLEAN-001",
        story_type="implementation",
        story_size="M",
        started_at=_NOW,
        completed_at=datetime(2026, 2, 1, tzinfo=UTC),
        qa_rounds=1,
        agentkit_version="3.0.0",
        agentkit_commit="abc",
    )
    reset_story = FactStory(
        project_key=_PROJECT,
        story_id="RESET-002",
        story_type="implementation",
        story_size="S",
        started_at=_NOW,
        completed_at=datetime(2026, 3, 1, tzinfo=UTC),
        qa_rounds=0,
        agentkit_version="3.0.0",
        agentkit_commit="def",
    )

    # Phase 1: before purge — both stories are in the repo.
    analytics_before = _make_kpi_analytics(stories=[clean_story, reset_story])
    app_before = _make_app(tmp_path, analytics_before)
    status_before, body_before = _get(
        app_before, f"/v1/projects/{_PROJECT}/kpi/stories", _PERIOD_QUERY
    )
    assert status_before == 200
    ids_before = [r["story_id"] for r in body_before["rows"]]
    assert "CLEAN-001" in ids_before, "Clean story must be present before purge"
    assert "RESET-002" in ids_before, "Reset story must be present before purge"

    # Phase 2: after purge — RESET-002 is deleted upstream; only CLEAN-001 remains.
    analytics_after = _make_kpi_analytics(stories=[clean_story])
    app_after = _make_app(tmp_path, analytics_after)
    status_after, body_after = _get(
        app_after, f"/v1/projects/{_PROJECT}/kpi/stories", _PERIOD_QUERY
    )
    assert status_after == 200
    ids_after = [r["story_id"] for r in body_after["rows"]]
    assert "CLEAN-001" in ids_after, "Clean story must still be present after purge"
    assert "RESET-002" not in ids_after, (
        "Purged reset story must NOT appear in KPI results (no late-query compensation)"
    )


def test_read_path_has_no_late_compensation_code(tmp_path: object) -> None:
    """AC6 + finding #11: the read path contains NO late-query compensation.

    Verifies by source inspection that neither KpiAnalytics.get_dashboard_view_with_filter
    nor the route handler contain inline reset-flag filtering logic.  The reset/purge
    chain is upstream (AG3-071/082); the read path only sees already-cleaned rows.
    """
    import inspect

    from agentkit.kpi_analytics import top as top_module
    from agentkit.kpi_analytics.http import routes as routes_module

    forbidden = ["reset_flag", "is_corrupt", "is_discarded", "late_compensat"]

    top_src = inspect.getsource(top_module.KpiAnalytics.get_dashboard_view_with_filter)
    routes_src = inspect.getsource(routes_module.KpiAnalyticsRoutes._handle_kpi_dimension)

    for pattern in forbidden:
        assert pattern not in top_src.lower(), (
            f"get_dashboard_view_with_filter must not contain late-compensation code "
            f"({pattern!r})"
        )
        assert pattern not in routes_src.lower(), (
            f"_handle_kpi_dimension must not contain late-compensation code ({pattern!r})"
        )


# ---------------------------------------------------------------------------
# Finding #2: comparison mode — second FactStore read must be performed
# ---------------------------------------------------------------------------


def test_comparison_period_triggers_second_factstore_read(tmp_path: object) -> None:
    """Finding #2 (AC5): comparison_period causes a second FactStore read with the comparison window.

    This test FAILS if the comparison read is removed: the comparison_rows in the
    response must contain the story that falls within the comparison period.
    """
    primary_story = FactStory(
        project_key=_PROJECT,
        story_id="PRIMARY-001",
        story_type="implementation",
        story_size="M",
        started_at=_NOW,
        completed_at=datetime(2026, 6, 1, tzinfo=UTC),
        qa_rounds=1,
        agentkit_version="3.0.0",
        agentkit_commit="abc",
    )
    comparison_story = FactStory(
        project_key=_PROJECT,
        story_id="COMP-002",
        story_type="implementation",
        story_size="S",
        started_at=datetime(2025, 1, 1, tzinfo=UTC),
        completed_at=datetime(2025, 6, 1, tzinfo=UTC),
        qa_rounds=2,
        agentkit_version="3.0.0",
        agentkit_commit="def",
    )
    analytics = _make_kpi_analytics(stories=[primary_story, comparison_story])
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/stories"
    # Primary period: 2026. Comparison period: 2025 (entirely before primary.start).
    compare_query = (
        f"{_PERIOD_QUERY}"
        "&compare_from=2025-01-01T00:00:00Z"
        "&compare_to=2025-12-31T00:00:00Z"
    )
    status, body = _get(app, path, compare_query)

    assert status == 200
    # Primary rows must include PRIMARY-001 (completed in 2026).
    primary_ids = [r["story_id"] for r in body["rows"]]
    assert "PRIMARY-001" in primary_ids
    assert "COMP-002" not in primary_ids  # out of primary period

    # comparison_rows must include COMP-002 (completed in 2025).
    assert "comparison_rows" in body, "comparison_rows must be present in response"
    comp_ids = [r["story_id"] for r in body["comparison_rows"]]
    assert "COMP-002" in comp_ids, (
        "COMP-002 must appear in comparison_rows (second FactStore read with comparison period)"
    )
    assert "PRIMARY-001" not in comp_ids  # out of comparison period


# ---------------------------------------------------------------------------
# Finding #6: project_key in query string is always rejected
# ---------------------------------------------------------------------------


def test_project_key_in_query_string_is_rejected(tmp_path: object) -> None:
    """Finding #6: project_key matching path key in query string → 400 (redundant)."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/stories"
    # project_key matches path key — still redundant, path is authoritative.
    bad_query = f"{_PERIOD_QUERY}&project_key={_PROJECT}"
    status, body = _get(app, path, bad_query)

    assert status == 400
    assert body["error_code"] == "invalid_kpi_filter"
    error_text = body.get("error", body.get("message", ""))
    assert "redundant" in error_text.lower() or "project_key" in error_text


def test_project_key_mismatch_in_query_string_returns_400(tmp_path: object) -> None:
    """Finding #6: project_key mismatching path key in query string → 400."""
    analytics = _make_kpi_analytics()
    app = _make_app(tmp_path, analytics)

    path = f"/v1/projects/{_PROJECT}/kpi/stories"
    bad_query = f"{_PERIOD_QUERY}&project_key=other-tenant"
    status, body = _get(app, path, bad_query)

    assert status == 400
    assert body["error_code"] == "invalid_kpi_filter"


# ---------------------------------------------------------------------------
# Finding #7: default builder must wire real KpiAnalytics
# ---------------------------------------------------------------------------


def test_default_builder_produces_wired_kpi_analytics_routes(tmp_path: object) -> None:
    """Finding #7: _build_default_kpi_analytics_routes returns a properly wired KpiAnalyticsRoutes.

    This test FAILS if _build_default_kpi_analytics_routes is changed to
    return KpiAnalyticsRoutes() without a real kpi_analytics.

    Verifies via ControlPlaneApplication default construction that the
    kpi_analytics_routes field has kpi_analytics != None.
    """
    import os

    from agentkit.control_plane_http.app import _build_default_kpi_analytics_routes

    # Set env so SQLite path is used (no Postgres needed in test).
    os.environ["AGENTKIT_STATE_BACKEND"] = "sqlite"
    os.environ["AGENTKIT_ALLOW_SQLITE"] = "1"
    os.environ.pop("AGENTKIT_STATE_DATABASE_URL", None)

    try:
        routes = _build_default_kpi_analytics_routes()
    finally:
        pass  # env reset handled by _reset_backend autouse fixture

    assert routes.kpi_analytics is not None, (
        "_build_default_kpi_analytics_routes must return KpiAnalyticsRoutes with "
        "kpi_analytics != None (breaking this causes all five KPI endpoints to 503)"
    )
