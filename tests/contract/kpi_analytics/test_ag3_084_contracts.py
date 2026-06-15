"""Contract tests for AG3-084 KPI-Trust-Boundary-Fix deliverables.

Pins the following contracts:
- EMPTY status: DashboardViewStatus.EMPTY enum value exists and is used for empty rollups.
- Reset rule: cleaned FactStore → empty result; no late-query compensation.
- DRIFT-fix: KpiAnalytics.get_dashboard_view no longer references StoryService.
- AC4: all five view kinds (story/guards/pools/pipeline/corpus) are real (no
  NotImplementedError) and ALL FIVE FactStore read methods are actually called with
  period predicates that flow through from the filter (finding #13 fix).
- AC8: no live endpoint exists; no StoryService/fact live-fallback.
- get_board regression: DashboardService.get_board still reads StoryService.
- KpiQueryFilter typed model: is a Pydantic BaseModel with expected fields.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from agentkit.kpi_analytics.catalog import KpiCatalog
from agentkit.kpi_analytics.fact_store.models import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStory,
    KpiQueryFilter,
    PeriodFilter,
)
from agentkit.kpi_analytics.top import KpiAnalytics
from agentkit.kpi_analytics.views import DashboardViewStatus

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_END = datetime(2026, 12, 31, tzinfo=UTC)
_PERIOD = PeriodFilter(start=_NOW, end=_END)


# ---------------------------------------------------------------------------
# DashboardViewStatus.EMPTY contract
# ---------------------------------------------------------------------------


def test_dashboard_view_status_has_empty_value() -> None:
    """Contract: DashboardViewStatus.EMPTY exists as a typed enum value."""
    assert hasattr(DashboardViewStatus, "EMPTY")
    assert DashboardViewStatus.EMPTY == "EMPTY"


def test_dashboard_view_status_still_has_ok_and_unavailable() -> None:
    """Contract: additive change — OK and UNAVAILABLE remain (no regressions)."""
    assert DashboardViewStatus.OK == "OK"
    assert DashboardViewStatus.UNAVAILABLE == "UNAVAILABLE"


def test_empty_rollup_yields_empty_status_not_ok() -> None:
    """Contract: empty FactStore rows → DashboardViewStatus.EMPTY (not OK)."""

    class _EmptyFactStore:
        def list_fact_stories(self, project_key: str, period: object = None) -> list[FactStory]:
            return []

    analytics = KpiAnalytics(catalog=KpiCatalog(), fact_store=_EmptyFactStore())
    view = analytics.get_dashboard_view("tenant-a", "story")

    assert view.status == DashboardViewStatus.EMPTY
    assert view.rows == []


def test_non_empty_rollup_yields_ok_status() -> None:
    """Contract: non-empty FactStore rows → DashboardViewStatus.OK."""
    story = FactStory(
        project_key="tenant-a",
        story_id="AG3-001",
        story_type="implementation",
        story_size="L",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        qa_rounds=1,
        agentkit_version="3.0.0",
        agentkit_commit="abc",
    )

    class _OneRowFactStore:
        def list_fact_stories(self, project_key: str, period: object = None) -> list[FactStory]:
            return [story]

    analytics = KpiAnalytics(catalog=KpiCatalog(), fact_store=_OneRowFactStore())
    view = analytics.get_dashboard_view("tenant-a", "story")

    assert view.status == DashboardViewStatus.OK
    assert len(view.rows) == 1


# ---------------------------------------------------------------------------
# AC4: all five view kinds are real and call the correct FactStore methods
# (finding #13 fix: assert that returned rows flow through for ALL five kinds)
# ---------------------------------------------------------------------------


class _SpyFactStore:
    """FactStore spy that records calls to all five list_fact_* methods.

    Returns one populated row per dimension so that rows genuinely flow through
    (EMPTY status would only prove the call was made; OK proves rows are passed).
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_fact_stories(
        self, project_key: str, period: PeriodFilter | None = None
    ) -> list[FactStory]:
        self.calls.append("list_fact_stories")
        return [
            FactStory(
                project_key=project_key,
                story_id="SPY-001",
                story_type="implementation",
                story_size="S",
                started_at=_NOW,
                qa_rounds=1,
                agentkit_version="0.0.0",
                agentkit_commit="spy",
            )
        ]

    def list_fact_guards(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactGuardPeriod]:
        self.calls.append("list_fact_guards")
        return [
            FactGuardPeriod(
                project_key=project_key,
                guard_id="spy-guard",
                period_start=period.start,
                period_end=period.end,
                invocation_count=1,
                violation_count=0,
            )
        ]

    def list_fact_pool(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactPoolPeriod]:
        self.calls.append("list_fact_pool")
        return [
            FactPoolPeriod(
                project_key=project_key,
                llm_role="spy-pool",
                period_start=period.start,
                period_end=period.end,
                call_count=1,
                token_input_total=100,
                token_output_total=50,
            )
        ]

    def list_fact_pipeline(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactPipelinePeriod]:
        self.calls.append("list_fact_pipeline")
        return [
            FactPipelinePeriod(
                project_key=project_key,
                period_start=period.start,
                period_end=period.end,
                stories_completed=1,
                stories_escalated=0,
            )
        ]

    def list_fact_corpus(
        self, project_key: str, period: PeriodFilter
    ) -> list[FactCorpusPeriod]:
        self.calls.append("list_fact_corpus")
        return [
            FactCorpusPeriod(
                project_key=project_key,
                period_start=period.start,
                period_end=period.end,
                incidents_recorded=1,
                patterns_promoted=0,
                checks_approved=1,
            )
        ]


def _make_filter(view_kind: str) -> KpiQueryFilter:
    """Build a KpiQueryFilter compatible with the given view_kind (no cross-dim filters)."""
    return KpiQueryFilter(
        project_key="tenant-a",
        period=_PERIOD,
    )


@pytest.mark.parametrize(
    "view_kind,expected_call",
    [
        ("story", "list_fact_stories"),
        ("guards", "list_fact_guards"),
        ("pools", "list_fact_pool"),
        ("pipeline", "list_fact_pipeline"),
        ("corpus", "list_fact_corpus"),
    ],
)
def test_all_five_view_kinds_call_correct_fact_store_method(
    view_kind: str, expected_call: str
) -> None:
    """Contract AC4 (finding #13 fix): each view_kind calls its own FactStore method.

    Rows returned by the spy flow through to the view — status=OK proves the
    call was made AND its return value was used (not replaced with hardcoded []).
    """
    spy = _SpyFactStore()
    analytics = KpiAnalytics(catalog=KpiCatalog(), fact_store=spy)
    kpi_filter = _make_filter(view_kind)
    view = analytics.get_dashboard_view_with_filter("tenant-a", view_kind, kpi_filter)

    assert expected_call in spy.calls, (
        f"Expected {expected_call} to be called for view_kind={view_kind!r}; "
        f"actual calls: {spy.calls}"
    )
    assert view.status == DashboardViewStatus.OK, (
        f"Expected OK (spy returned one row); got {view.status!r} for view_kind={view_kind!r}"
    )
    assert len(view.rows) == 1, (
        f"Expected 1 row for view_kind={view_kind!r}; got {len(view.rows)}"
    )


def test_story_view_kind_is_real_via_get_dashboard_view() -> None:
    """Contract AC4: 'story' view kind works via get_dashboard_view (no FactStore read needed for filter)."""

    class _EmptyFactStore:
        def list_fact_stories(self, project_key: str, period: object = None) -> list[FactStory]:
            return []

    analytics = KpiAnalytics(catalog=KpiCatalog(), fact_store=_EmptyFactStore())
    # 'story' is the only dimension that works without a PeriodFilter.
    view = analytics.get_dashboard_view("tenant-a", "story")
    assert view.view_name == "story"


@pytest.mark.parametrize("view_kind", ["guards", "pools", "pipeline", "corpus"])
def test_period_rollup_view_kinds_require_filter(view_kind: str) -> None:
    """Contract AC4 (Finding #3): period-rollup dimensions raise ValueError without a PeriodFilter.

    These four dimensions MUST use get_dashboard_view_with_filter.  Returning
    EMPTY without a real FactStore read would violate the invariant
    'EMPTY must ONLY reflect a real zero-row FactStore read.'
    """

    class _EmptyFactStore:
        def list_fact_stories(self, project_key: str, period: object = None) -> list[FactStory]:
            return []

    analytics = KpiAnalytics(catalog=KpiCatalog(), fact_store=_EmptyFactStore())
    with pytest.raises(ValueError, match="use get_dashboard_view_with_filter"):
        analytics.get_dashboard_view("tenant-a", view_kind)


def test_unknown_view_kind_raises_value_error_not_not_implemented() -> None:
    """Contract: unknown view_kind raises ValueError (fail-closed); NOT NotImplementedError."""

    class _EmptyFactStore:
        def list_fact_stories(self, project_key: str, period: object = None) -> list[FactStory]:
            return []

    analytics = KpiAnalytics(catalog=KpiCatalog(), fact_store=_EmptyFactStore())
    with pytest.raises(ValueError):
        analytics.get_dashboard_view("tenant-a", "live")


# ---------------------------------------------------------------------------
# AC8: no live endpoint / no StoryService live-fallback
# ---------------------------------------------------------------------------


def test_kpi_analytics_top_does_not_import_story_service() -> None:
    """Contract AC8: kpi_analytics.top module does NOT import StoryService.

    The live-read path via StoryService is out of scope (§2.2).  This
    contract pins that the top-level module's imports stay clean — it
    checks the module's actual imports (not docstrings that may reference
    StoryService as a negative example).
    """
    import agentkit.kpi_analytics.top as top_module

    # Check imports in the module, not docstrings.
    # StoryService must not be imported (directly or transitively at module level).
    imported_names = list(vars(top_module).keys())
    # Confirm StoryService is not a name in the top module namespace.
    assert "StoryService" not in imported_names, (
        "kpi_analytics.top must NOT import StoryService; "
        "live-read port is not implemented (AG3-084 §2.2)"
    )
    # Also confirm agentkit.story is not a direct module-level import
    # (only TYPE_CHECKING imports are acceptable, which don't execute).
    story_module = vars(top_module).get("agentkit")
    assert story_module is None, (
        "kpi_analytics.top must NOT have a module-level 'agentkit' reference via story import"
    )


def test_kpi_analytics_http_routes_does_not_import_story_service() -> None:
    """Contract AC8: kpi_analytics.http.routes module does NOT import StoryService."""
    import agentkit.kpi_analytics.http.routes as routes_module

    source = inspect.getsource(routes_module)
    assert "StoryService" not in source, (
        "kpi_analytics.http.routes must NOT reference StoryService"
    )


# ---------------------------------------------------------------------------
# DRIFT-fix: get_story_metrics no longer borrows StoryService in KPI path
# ---------------------------------------------------------------------------


def test_get_story_metrics_does_not_call_story_service_list_stories() -> None:
    """Contract DRIFT-AG3-038 fix: get_story_metrics reads FactStore, not StoryService.

    A spy StoryService that raises on list_stories() must NOT be triggered.
    """
    from agentkit.kpi_analytics.dashboard.service import DashboardService
    from agentkit.story.models import StoryListResponse  # noqa: TC001
    from agentkit.story.service import StoryService

    class _SpyStoryService(StoryService):
        def list_stories(self, project_key: str) -> StoryListResponse:
            raise AssertionError(
                "DRIFT-AG3-038: get_story_metrics MUST NOT call StoryService.list_stories"
            )

    class _EmptyFactStore:
        def list_fact_stories(self, project_key: str, period: object = None) -> list[FactStory]:
            return []

    service = DashboardService(
        story_service=_SpyStoryService(),
        fact_store=_EmptyFactStore(),
    )
    # Must not raise (StoryService.list_stories must not be called).
    result = service.get_story_metrics("tenant-a")
    assert result.stories == []


def test_get_board_still_reads_story_service() -> None:
    """Contract regression: get_board (live Kanban) still uses StoryService.list_stories."""
    from agentkit.kpi_analytics.dashboard.service import DashboardService
    from agentkit.story.models import StoryListResponse
    from agentkit.story.service import StoryService

    called: list[str] = []

    class _TracingStoryService(StoryService):
        def list_stories(self, project_key: str) -> StoryListResponse:
            called.append(project_key)
            return StoryListResponse(project_key=project_key, stories=[])

    service = DashboardService(story_service=_TracingStoryService())
    service.get_board("tenant-a")

    assert called == ["tenant-a"], "get_board must call StoryService.list_stories"


# ---------------------------------------------------------------------------
# Reset rule: cleaned-vs-uncleaned FactStore contract
# ---------------------------------------------------------------------------


def test_reset_story_purged_upstream_is_absent_from_kpi() -> None:
    """Contract (Finding #4): purged reset story is absent; no late-query compensation.

    Phase 1 — before purge: BOTH clean and reset stories are present in the FactStore.
    Phase 2 — after purge: only the clean story remains.
    The service must:
    - Return both stories when both are present.
    - Return ONLY the clean story after the purge.
    - NOT apply any late-query compensation.
    """
    from datetime import UTC, datetime

    from agentkit.kpi_analytics.dashboard.service import DashboardService

    clean_story = FactStory(
        project_key="tenant-a",
        story_id="CLEAN-001",
        story_type="implementation",
        story_size="M",
        started_at=datetime(2026, 5, 1, tzinfo=UTC),
        completed_at=datetime(2026, 5, 10, tzinfo=UTC),
        qa_rounds=1,
        agentkit_version="3.0.0",
        agentkit_commit="abc",
    )
    reset_story = FactStory(
        project_key="tenant-a",
        story_id="RESET-002",
        story_type="implementation",
        story_size="S",
        started_at=datetime(2026, 4, 1, tzinfo=UTC),
        completed_at=datetime(2026, 4, 10, tzinfo=UTC),
        qa_rounds=0,
        agentkit_version="3.0.0",
        agentkit_commit="def",
    )

    # Phase 1: before purge — both stories present.
    class _DirtyFactStore:
        def list_fact_stories(self, project_key: str, period: object = None) -> list[FactStory]:
            return [clean_story, reset_story]

    service_before = DashboardService(fact_store=_DirtyFactStore())
    response_before = service_before.get_story_metrics("tenant-a")
    ids_before = [item.story_id for item in response_before.stories]
    assert "CLEAN-001" in ids_before, "Clean story must be present before purge"
    assert "RESET-002" in ids_before, "Reset story must be present before purge"

    # Phase 2: after purge — RESET-002 deleted upstream; only CLEAN-001 remains.
    class _CleanedFactStore:
        """Simulates a FactStore that has been purged of reset/corrupted runs."""

        def list_fact_stories(self, project_key: str, period: object = None) -> list[FactStory]:
            # The reset story (RESET-002) is absent — purged upstream by AG3-071/082.
            return [clean_story]

    service_after = DashboardService(fact_store=_CleanedFactStore())
    response_after = service_after.get_story_metrics("tenant-a")
    ids_after = [item.story_id for item in response_after.stories]
    assert "CLEAN-001" in ids_after, "Clean story must still be present after purge"
    assert "RESET-002" not in ids_after, (
        "Purged reset story must not appear in KPI results (no late-query compensation)"
    )


def test_no_late_query_fix_in_get_story_metrics_source() -> None:
    """Contract: get_story_metrics does NOT perform inline late-query compensation.

    The reset/purge chain is upstream (AG3-071/082).  The service only reads
    the already-cleaned FactStore — it must NOT contain code that explicitly
    filters on a 'reset_flag', 'is_corrupt', 'is_discarded', or equivalent
    runtime compensation column.  (Docstring mentions of 'reset' or 'purge'
    are documentation, not compensating logic.)
    """
    from agentkit.kpi_analytics.dashboard import service as svc_module

    source = inspect.getsource(svc_module.DashboardService.get_story_metrics)
    # Compensating query logic keywords that would indicate an inline late-fix.
    forbidden_patterns = ["reset_flag", "is_corrupt", "is_discarded", "late_compensat"]
    for pattern in forbidden_patterns:
        assert pattern not in source.lower(), (
            f"get_story_metrics must not contain late-query compensation code ({pattern!r})"
        )


# ---------------------------------------------------------------------------
# KpiQueryFilter typed model contract
# ---------------------------------------------------------------------------


def test_kpi_query_filter_is_pydantic_base_model() -> None:
    """Contract: KpiQueryFilter is a Pydantic BaseModel (typed, not a dict)."""
    from pydantic import BaseModel

    assert issubclass(KpiQueryFilter, BaseModel)


def test_kpi_query_filter_fields_match_spec() -> None:
    """Contract: KpiQueryFilter has the required FK-63 §63.4.2 fields."""
    fields = KpiQueryFilter.model_fields
    assert "project_key" in fields
    assert "period" in fields
    assert "entity_filter" in fields
    assert "story_filter" in fields
    assert "comparison_period" in fields


def test_kpi_query_filter_period_is_required() -> None:
    """Contract: period is a required field (no default)."""

    import pytest as _pytest
    from pydantic import ValidationError

    with _pytest.raises(ValidationError):
        KpiQueryFilter(project_key="tenant-a")  # type: ignore[call-arg]


def test_period_filter_fields() -> None:
    """Contract: PeriodFilter has start and end fields."""
    fields = PeriodFilter.model_fields
    assert "start" in fields
    assert "end" in fields
