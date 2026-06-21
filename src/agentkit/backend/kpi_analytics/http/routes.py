"""KPI analytics HTTP routes (AG3-090, AG3-084, FK-72 §72.8.2).

Mounts under ``/v1/projects/{project_key}/kpi`` (PO decision 2026-06-08,
per AG3-084 / AG3-094 / FK-63).

Endpoints:
  GET /v1/projects/{key}/kpi/stories       -- story KPI dimension (fact_story)
  GET /v1/projects/{key}/kpi/guards        -- guards KPI dimension (fact_guard_period)
  GET /v1/projects/{key}/kpi/pools         -- pools KPI dimension (fact_pool_period)
  GET /v1/projects/{key}/kpi/pipeline      -- pipeline KPI dimension (fact_pipeline_period)
  GET /v1/projects/{key}/kpi/corpus        -- failure-corpus KPI dimension (fact_corpus_period)
  GET /v1/projects/{key}/kpi/design-tokens -- FK-64 design token set (AG3-092)

All five KPI dimension endpoints read from Fact-Rollups (FactStore) via
``KpiAnalytics.get_dashboard_view_with_filter``.  They parse a typed
``KpiQueryFilter`` from query parameters (FK-63 §63.4.2) and apply
fail-closed validation.  The design-token route is a static adapter with
no backend dependency (AG3-092, FK-64 §64.2).

Project/tenant scope (FK-63 §63.3.1): ``project_key`` is extracted from the
URL path and is mandatory.  There is no unscoped cross-project query path.

Parameter validation (fail-closed):
- Period (``from``/``to``) is MANDATORY for all five dimension endpoints.
  A missing period is rejected with ``400 invalid_kpi_filter`` — no
  full-table scan is performed without an explicit time bound.
- ``from`` and ``to`` must be timezone-aware ISO-8601 timestamps (Z or
  explicit offset).  Naive timestamps are rejected with ``400``.
- Unknown query parameters are rejected with ``400 invalid_kpi_filter``.
- Duplicate/multivalued parameters are rejected with ``400``.
- Path ``project_key`` and query-string ``project_key`` mismatch is rejected
  with ``400``.
- ``compare_from``/``compare_to`` are parsed into ``KpiQueryFilter.comparison_period``
  when provided (AC5 comparison mode).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Literal

from agentkit.backend.control_plane.models import (
    BcRouteResponse,
    bc_error_response,
    bc_json_response,
    bc_unavailable_response,
)
from agentkit.backend.kpi_analytics.design_system import get_design_system
from agentkit.backend.kpi_analytics.http.wire_dto import map_fact_row_to_wire

if TYPE_CHECKING:
    from agentkit.backend.kpi_analytics.fact_store.models import KpiQueryFilter, PeriodFilter
    from agentkit.backend.kpi_analytics.top import KpiAnalytics
    from agentkit.backend.kpi_analytics.views import DashboardView

logger = logging.getLogger(__name__)

# Route for KPI dimensions (stories / guards / pools / pipeline / corpus)
_KPI_DIMENSION_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/kpi"
    r"(?:/(?P<dimension>stories|guards|pools|pipeline|corpus))?/?$"
)

# Static design-token route (AG3-092, FK-64 §64.2)
_KPI_DESIGN_TOKENS_PATH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/kpi/design-tokens/?$"
)

KpiDimension = Literal["stories", "guards", "pools", "pipeline", "corpus"]
KpiAnalyticsRouteResponse = BcRouteResponse

# Map URL dimension segment → internal view_kind used by KpiAnalytics.get_dashboard_view*.
# URL uses plural "stories" (REST convention); internal view_kind is singular "story"
# (fact_story table naming).
_DIMENSION_TO_VIEW_KIND: dict[str, str] = {
    "stories": "story",
    "guards": "guards",
    "pools": "pools",
    "pipeline": "pipeline",
    "corpus": "corpus",
}

# Allowed query parameters for the five KPI dimension endpoints (fail-closed).
# Unknown params are rejected with 400 invalid_kpi_filter.
# ``project_key`` is explicitly included so the mismatch/redundancy check below
# can fire; the path parameter is always authoritative and any query-string
# ``project_key`` is rejected with 400 (redundant or mismatching).
_ALLOWED_KPI_PARAMS: frozenset[str] = frozenset(
    [
        "from",
        "to",
        "compare_from",
        "compare_to",
        "guard",
        "pool",
        "story_type",
        "story_size",
        "project_key",
    ]
)


@dataclass(frozen=True)
class KpiAnalyticsRoutes:
    """Route handler for the kpi-analytics BC HTTP surface (AG3-084).

    Wires the five KPI dimension endpoints onto ``KpiAnalytics`` with real
    FactStore reads.  The design-token route (AG3-092, FK-64 §64.2) is a
    thin static adapter with no backend dependency.

    Fail-closed: when ``kpi_analytics`` is not configured, ALL five KPI
    dimension endpoints return ``503 kpi_unavailable``.  No stub/compat path
    is provided — a misconfigured composition root fails loudly.

    Args:
        kpi_analytics: Optional ``KpiAnalytics`` facade (with ``fact_store``
            configured).  When ``None``, the five KPI dimension endpoints
            return ``503 kpi_unavailable`` (fail-closed).  The design-token
            route is ALWAYS available regardless of this parameter.
    """

    kpi_analytics: KpiAnalytics | None = field(default=None)

    def handle_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> KpiAnalyticsRouteResponse | None:
        """Handle KPI GET routes or return None.

        Matches the design-token route first (static, no backend), then the
        five KPI dimension sub-resources.

        Args:
            route_path: Resolved URL path from the control-plane dispatcher.
            query: Parsed query-string parameters (``parse_qs`` output).
            correlation_id: Request correlation ID for tracing.

        Returns:
            ``BcRouteResponse`` when the route is claimed, ``None`` otherwise.
        """
        # Design-token route: always available, no kpi_analytics guard.
        dt_match = _KPI_DESIGN_TOKENS_PATH.match(route_path)
        if dt_match is not None:
            return self._handle_design_tokens(
                dt_match.group("project_key"), correlation_id
            )

        dim_match = _KPI_DIMENSION_PATH.match(route_path)
        if dim_match is None:
            return None

        project_key = dim_match.group("project_key")
        dimension = dim_match.group("dimension")

        # Fail-closed: kpi_analytics must be configured (no compat stub).
        if self.kpi_analytics is None:
            return bc_unavailable_response(
                "kpi_unavailable",
                message="KPI analytics service is not available (business logic: AG3-084)",
                correlation_id=correlation_id,
            )

        # --- Real KPI read path (AG3-084) ---
        return self._handle_kpi_dimension(
            project_key=project_key,
            dimension=dimension,
            query=query,
            correlation_id=correlation_id,
        )

    def handle_post(
        self,
        _route_path: str,
        _payload: object,
        _correlation_id: str,
    ) -> KpiAnalyticsRouteResponse | None:
        """Handle KPI POST routes or return None (KPI surface is read-only)."""
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _handle_kpi_dimension(
        self,
        *,
        project_key: str,
        dimension: str | None,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> KpiAnalyticsRouteResponse:
        """Dispatch a KPI dimension GET to FactStore via KpiAnalytics.

        Parses a ``KpiQueryFilter`` from query parameters (fail-closed):
        - Unknown or duplicate query params → 400 invalid_kpi_filter.
        - Missing ``from``/``to`` period → 400 invalid_kpi_filter
          (period is mandatory; no full-table scan without a time bound).
        - Naive datetimes → 400 (must be timezone-aware ISO-Z or +offset).
        - Path ``project_key`` / query ``project_key`` mismatch → 400.
        - ``compare_from``/``compare_to`` are parsed into
          ``KpiQueryFilter.comparison_period`` for AC5 comparison mode.

        Args:
            project_key: Project scope from the URL path.
            dimension: KPI dimension (``stories``/``guards``/…) or ``None``
                for the root ``/kpi`` endpoint.
            query: Parsed query string (parse_qs output — each key maps to a
                list of values; duplicate params appear as multi-element lists).
            correlation_id: Request correlation ID.

        Returns:
            ``BcRouteResponse`` with the KPI view payload.
        """
        assert self.kpi_analytics is not None  # guarded by caller

        param_error = self._validate_kpi_query_params(
            project_key=project_key, query=query, correlation_id=correlation_id
        )
        if param_error is not None:
            return param_error

        kpi_filter, filter_error = self._parse_kpi_filter(
            project_key=project_key, query=query, correlation_id=correlation_id
        )
        if filter_error is not None:
            return filter_error
        assert kpi_filter is not None  # no error ⇒ filter built

        url_dimension = dimension or "stories"
        view_kind = _DIMENSION_TO_VIEW_KIND.get(url_dimension, url_dimension)
        try:
            view = self.kpi_analytics.get_dashboard_view_with_filter(
                project_key, view_kind, kpi_filter
            )
        except ValueError as exc:
            return bc_error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_kpi_view_kind",
                message=str(exc),
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("KPI dimension read failed: %s", exc)
            return bc_unavailable_response(
                "kpi_unavailable",
                message=str(exc),
                correlation_id=correlation_id,
            )

        return bc_json_response(
            HTTPStatus.OK,
            self._build_kpi_payload(view, url_dimension, kpi_filter.comparison_period),
            correlation_id=correlation_id,
        )

    def _validate_kpi_query_params(
        self,
        *,
        project_key: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> KpiAnalyticsRouteResponse | None:
        """Fail-closed query-parameter validation.

        Returns an error ``BcRouteResponse`` for the first violation, or ``None``
        when the parameters are well-formed.  Rejects unknown params, duplicate/
        multivalued params, and any query-string ``project_key`` (the path
        parameter is the only authoritative scope key).
        """
        unknown_params = set(query.keys()) - _ALLOWED_KPI_PARAMS
        if unknown_params:
            return bc_error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_kpi_filter",
                message=(
                    f"Unknown query parameter(s): {sorted(unknown_params)!r}. "
                    f"Allowed: {sorted(_ALLOWED_KPI_PARAMS)!r}."
                ),
                correlation_id=correlation_id,
            )

        for param_name, values in query.items():
            if len(values) > 1:
                return bc_error_response(
                    HTTPStatus.BAD_REQUEST,
                    error_code="invalid_kpi_filter",
                    message=(
                        f"Duplicate query parameter {param_name!r}: "
                        f"each parameter must appear at most once."
                    ),
                    correlation_id=correlation_id,
                )

        # Reject any query-string project_key (path is always authoritative);
        # a matching value is redundant, a mismatch is a conflict — both → 400.
        if "project_key" not in query:
            return None
        query_project_key = query["project_key"][0]
        if query_project_key != project_key:
            return bc_error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_kpi_filter",
                message=(
                    f"project_key mismatch: path has {project_key!r} but "
                    f"query string has {query_project_key!r}. "
                    f"Use the path parameter only."
                ),
                correlation_id=correlation_id,
            )
        return bc_error_response(
            HTTPStatus.BAD_REQUEST,
            error_code="invalid_kpi_filter",
            message=(
                "project_key in query string is redundant; "
                "use the path parameter only."
            ),
            correlation_id=correlation_id,
        )

    def _parse_kpi_filter(
        self,
        *,
        project_key: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> tuple[KpiQueryFilter | None, KpiAnalyticsRouteResponse | None]:
        """Parse a typed ``KpiQueryFilter`` from query params (fail-closed).

        Returns ``(filter, None)`` on success or ``(None, error_response)`` on any
        validation failure: missing mandatory period, naive timestamps, a
        malformed comparison window, or an invalid filter combination.
        """
        from agentkit.backend.kpi_analytics.fact_store.models import (
            EntityFilter,
            KpiQueryFilter,
            PeriodFilter,
            StoryFilter,
        )

        from_vals = query.get("from", [])
        to_vals = query.get("to", [])
        # Period is MANDATORY — reject missing period with 400 (no full-table scan).
        if not from_vals or not to_vals:
            return None, bc_error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_kpi_filter",
                message=(
                    "Both 'from' and 'to' query parameters are required. "
                    "Period is mandatory for all KPI dimension endpoints "
                    "(FK-63 §63.3.3 — no unbounded full-table scan allowed)."
                ),
                correlation_id=correlation_id,
            )

        # Parse and validate period timestamps — must be timezone-aware.
        try:
            period_start = _parse_aware_datetime(from_vals[0], "'from'")
            period_end = _parse_aware_datetime(to_vals[0], "'to'")
        except ValueError as exc:
            return None, bc_error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_kpi_filter",
                message=str(exc),
                correlation_id=correlation_id,
            )

        comparison_period, comparison_error = self._parse_comparison_period(
            query=query, correlation_id=correlation_id
        )
        if comparison_error is not None:
            return None, comparison_error

        # Optional entity / story filters (single values — duplicates already rejected).
        guard_raw = query.get("guard", [None])[0] or None
        pool_raw = query.get("pool", [None])[0] or None
        story_type_raw = query.get("story_type", [None])[0] or None
        story_size_raw = query.get("story_size", [None])[0] or None

        try:
            kpi_filter = KpiQueryFilter(
                project_key=project_key,
                period=PeriodFilter(start=period_start, end=period_end),
                entity_filter=EntityFilter(guard=guard_raw, pool=pool_raw),
                story_filter=StoryFilter(
                    story_type=story_type_raw,
                    story_size=story_size_raw,
                ),
                comparison_period=comparison_period,
            )
        except (ValueError, TypeError) as exc:
            return None, bc_error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_kpi_filter",
                message=f"Invalid KPI query filter: {exc}",
                correlation_id=correlation_id,
            )
        return kpi_filter, None

    def _parse_comparison_period(
        self,
        *,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> tuple[PeriodFilter | None, KpiAnalyticsRouteResponse | None]:
        """Parse the optional AC5 comparison window from query params (fail-closed).

        Returns ``(None, None)`` when no comparison window is requested,
        ``(period, None)`` on success, or ``(None, error_response)`` when only one
        bound is supplied or a bound is naive/malformed.
        """
        from agentkit.backend.kpi_analytics.fact_store.models import PeriodFilter

        compare_from_vals = query.get("compare_from", [])
        compare_to_vals = query.get("compare_to", [])
        if not compare_from_vals and not compare_to_vals:
            return None, None
        if not compare_from_vals or not compare_to_vals:
            return None, bc_error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_kpi_filter",
                message=(
                    "Both 'compare_from' and 'compare_to' must be provided together "
                    "when using comparison mode."
                ),
                correlation_id=correlation_id,
            )
        try:
            compare_start = _parse_aware_datetime(compare_from_vals[0], "'compare_from'")
            compare_end = _parse_aware_datetime(compare_to_vals[0], "'compare_to'")
            comparison_period = PeriodFilter(start=compare_start, end=compare_end)
        except ValueError as exc:
            return None, bc_error_response(
                HTTPStatus.BAD_REQUEST,
                error_code="invalid_kpi_filter",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return comparison_period, None

    @staticmethod
    def _build_kpi_payload(
        view: DashboardView,
        url_dimension: str,
        comparison_period: PeriodFilter | None,
    ) -> dict[str, object]:
        """Serialize a ``DashboardView`` to the wire payload at the HTTP edge.

        Typed fact rows are mapped through FK-62-named wire DTOs here (the same
        edge pattern as ``_handle_design_tokens``).  The comparison block is
        included only when a comparison window was requested (AC5).
        """
        payload: dict[str, object] = {
            "project_key": view.project_key,
            "dimension": url_dimension,
            "status": view.status,
            "rows": [map_fact_row_to_wire(row) for row in view.rows],
        }
        if comparison_period is not None:
            payload["comparison_period"] = {
                "from": comparison_period.start.isoformat(),
                "to": comparison_period.end.isoformat(),
            }
            payload["comparison_rows"] = [
                map_fact_row_to_wire(row) for row in view.comparison_rows
            ]
        return payload

    @staticmethod
    def _handle_design_tokens(
        project_key: str,
        correlation_id: str,
    ) -> BcRouteResponse:
        """Thin static adapter: serialize the deterministic DesignSystem owner.

        FK-64 §64.2: no dynamic computation; this is a pure serialization of
        the typed token owner.  The ``project_key`` is echoed in the response
        for consumer orientation but does NOT affect the token values (tokens
        are global, not project-scoped).

        Args:
            project_key: Project scope from URL (echoed in response only).
            correlation_id: Request correlation ID.

        Returns:
            ``BcRouteResponse`` with the full token family tree.
        """
        ds = get_design_system()
        payload: dict[str, object] = {
            "project_key": project_key,
            "colors": ds.colors.model_dump(mode="json"),
            "typography": ds.typography.model_dump(mode="json"),
            "spacing": ds.spacing.model_dump(mode="json"),
            "control": ds.control.model_dump(mode="json"),
            "chart": ds.chart.model_dump(mode="json"),
        }
        return bc_json_response(HTTPStatus.OK, payload, correlation_id=correlation_id)


def _parse_aware_datetime(value: str, param_label: str) -> datetime:
    """Parse an ISO-8601 timestamp and require timezone-awareness.

    Accepts "Z" suffix (UTC) or explicit offset ("+HH:MM"/"-HH:MM").
    Rejects naive datetimes (no timezone info) with a descriptive ValueError
    so callers can return a 400 response (fail-closed).

    Args:
        value: Raw ISO-8601 string from a query parameter.
        param_label: Human-readable parameter label for error messages
            (e.g. ``"'from'"``).

    Returns:
        Timezone-aware ``datetime``.

    Raises:
        ValueError: When the value cannot be parsed or is timezone-naive.
    """
    # Replace trailing "Z" with "+00:00" for fromisoformat compatibility.
    normalised = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(normalised)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Invalid ISO-8601 timestamp for {param_label}: {value!r} — {exc}"
        ) from exc
    if dt.tzinfo is None:
        raise ValueError(
            f"Timezone-naive timestamp for {param_label}: {value!r}. "
            f"Timestamps must include a timezone offset (e.g. '2026-01-01T00:00:00Z' "
            f"or '2026-01-01T00:00:00+00:00'). Naive datetimes are rejected "
            f"(fail-closed — ambiguous UTC vs. local time)."
        )
    return dt
