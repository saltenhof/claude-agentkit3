"""Grounded bounded-context route dispatch (AG3-090), split out of the app.

Extracted from :class:`ControlPlaneApplication` so that transport class stays
within the per-class LOC budget (``PY_CLASS_MAX_LOC_800``) WITHOUT any
behaviour change -- the same reason and the same shape as
:class:`_GovernanceMediationHandlers`.

Every bounded context that grounds its routes here grows that class again:
AG3-239 and AG3-241 each pushed it past the budget, and the fix each time was
to move a dispatcher next to what it dispatches to. These two depend only on
the injected route objects, never on the app's own routing state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.control_plane_http.responses import (
    _bc_response_to_http_response,
)

if TYPE_CHECKING:
    from agentkit.backend.auth.middleware import AuthResult
    from agentkit.backend.control_plane_http.failure_corpus_routes import (
        FailureCorpusRoutes,
    )
    from agentkit.backend.control_plane_http.responses import HttpResponse
    from agentkit.backend.kpi_analytics.http.routes import KpiAnalyticsRoutes
    from agentkit.backend.task_management.http.routes import TaskManagementRoutes


class _GroundedBcDispatchMixin:
    """GET/POST dispatch onto the grounded BC ``http/`` route modules."""

    _kpi_analytics_routes: KpiAnalyticsRoutes
    _task_management_routes: TaskManagementRoutes
    _failure_corpus_routes: FailureCorpusRoutes

    def _dispatch_new_bc_get(
        self,
        route_path: str,
        query: dict[str, list[str]],
        correlation_id: str,
    ) -> HttpResponse | None:
        """Dispatch GET to the BC http/ modules (AG3-090)."""
        for routes in (
            self._kpi_analytics_routes,
            self._task_management_routes,
        ):
            response = routes.handle_get(route_path, query, correlation_id)
            if response is not None:
                return _bc_response_to_http_response(response)
        return None


    def _dispatch_new_bc_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
        auth_result: AuthResult | None,
    ) -> HttpResponse | None:
        """Dispatch POST to the grounded BC http/ modules (AG3-090)."""
        for routes in (
            self._kpi_analytics_routes,
            self._task_management_routes,
        ):
            response = routes.handle_post(route_path, payload, correlation_id)
            if response is not None:
                return _bc_response_to_http_response(response)
        return self._failure_corpus_routes.handle_post(
            route_path,
            payload,
            correlation_id,
            auth_result,
        )

