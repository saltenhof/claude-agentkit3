"""Default route composition for the control-plane HTTP BFF."""


from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:

    from agentkit.backend.auth.http.routes import AuthRoutes
    from agentkit.backend.auth.middleware import AuthMiddleware
    from agentkit.backend.concept_catalog.http.routes import ConceptCatalogRoutes
    from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
    from agentkit.backend.execution_planning.http.routes import ExecutionPlanningRoutes
    from agentkit.backend.kpi_analytics.http.routes import KpiAnalyticsRoutes
    from agentkit.backend.project_management.http.routes import ProjectManagementRoutes
    from agentkit.backend.project_management.read_model_routes import ReadModelRoutes
    from agentkit.backend.story.service import StoryService
    from agentkit.backend.story_context_manager.http.routes import StoryContextRoutes
    from agentkit.backend.task_management.http.routes import TaskManagementRoutes
    from agentkit.backend.telemetry.http.routes import TelemetryRoutes
    from agentkit.integration_clients.multi_llm_hub.http.routes import MultiLlmHubRoutes


def _build_default_story_service() -> StoryService:
    """Build the BFF story read service through the Story-BC ``StoryReadPort``.

    FK-07 §7.6: the default wiring routes story list/detail reads through the
    published port adapter (composition root), never a state-backend passthrough.
    """
    from agentkit.backend.bootstrap.composition_root import build_story_read_service

    return build_story_read_service()


def _build_default_runtime_service() -> ControlPlaneRuntimeService:
    """Build the productive control-plane runtime through the composition root."""
    from agentkit.backend.bootstrap.composition_root import (
        build_control_plane_runtime_service,
    )

    return cast("ControlPlaneRuntimeService", build_control_plane_runtime_service())


def _build_default_project_routes() -> ProjectManagementRoutes:
    from agentkit.backend.bootstrap.composition_root import build_project_repository
    from agentkit.backend.project_management.http.routes import ProjectManagementRoutes
    from agentkit.backend.story_context_manager.service import (
        StoryService as StoryContextStoryService,
    )

    _ctx_service: list[StoryContextStoryService | None] = [None]

    def _repos_in_use_checker(
        project_key: str,
        repos: list[str],
    ) -> list[str]:
        svc = _ctx_service[0]
        if svc is None:
            svc = StoryContextStoryService()
            _ctx_service[0] = svc
        in_use = svc.list_active_repos(project_key)
        return [r for r in repos if r in in_use]

    # FK-07 §7.6/§7.9 (AG3-127): the BFF composition root owns the project read
    # adapter wiring — inject the ``ProjectRepository`` port through the
    # composition root instead of relying on the BC-internal default.
    return ProjectManagementRoutes(
        repos_in_use_checker=_repos_in_use_checker,
        repository=build_project_repository(),
    )


def _build_default_story_routes() -> StoryContextRoutes:
    from agentkit.backend.story_context_manager.http.routes import StoryContextRoutes

    return StoryContextRoutes()


def _build_default_concept_routes() -> ConceptCatalogRoutes:
    from agentkit.backend.concept_catalog.http.routes import ConceptCatalogRoutes

    return ConceptCatalogRoutes()


def _build_default_hub_routes() -> MultiLlmHubRoutes:
    from agentkit.integration_clients.multi_llm_hub.http.routes import MultiLlmHubRoutes

    return MultiLlmHubRoutes()


def _build_default_planning_routes() -> ExecutionPlanningRoutes:
    from agentkit.backend.execution_planning.http.routes import ExecutionPlanningRoutes

    return ExecutionPlanningRoutes()


def _build_default_telemetry_routes() -> TelemetryRoutes:
    from agentkit.backend.bootstrap.composition_root import (
        build_project_telemetry_event_source,
    )
    from agentkit.backend.telemetry.http.routes import TelemetryRoutes

    # FK-07 §7.6/§7.8 (AG3-127): the BFF composition root owns the telemetry read
    # adapter wiring — inject the ``ProjectTelemetryEventSource`` port; the
    # telemetry BC no longer self-instantiates a state-backend adapter.
    return TelemetryRoutes(build_project_telemetry_event_source())


def _build_default_auth_routes(auth_middleware: AuthMiddleware | None) -> AuthRoutes:
    from agentkit.backend.auth.http.routes import AuthRoutes

    if auth_middleware is not None:
        return AuthRoutes(
            session_store=auth_middleware.session_store,
            token_repository=auth_middleware.token_repository,
        )
    return AuthRoutes()


def _build_default_kpi_analytics_routes() -> KpiAnalyticsRoutes:
    """Build the default KpiAnalyticsRoutes backed by a real FactStore.

    Wires ``StateBackendFactRepository`` (the production SQLite/Postgres
    adapter) into a real ``FactStore`` and ``KpiAnalytics`` so that the five
    KPI dimension endpoints read live data from the fact tables.  This is the
    composition root for the kpi_analytics BC (AC1/AC3 — real FactStore reads,
    not a stub).

    The ``KpiCatalog`` and ``FactStore`` are the minimal dependencies required
    for ``KpiAnalytics``; the optional ``RefreshWorker`` is omitted here
    (refresh is triggered by the closure pipeline, not by the HTTP read path).
    """
    from agentkit.backend.bootstrap.composition_root import build_kpi_analytics_read_facade
    from agentkit.backend.kpi_analytics.http.routes import KpiAnalyticsRoutes

    return KpiAnalyticsRoutes(kpi_analytics=build_kpi_analytics_read_facade())


def _build_default_task_management_routes() -> TaskManagementRoutes:
    """Build the default task-management BC route handler backed by real storage."""
    from agentkit.backend.bootstrap.composition_root import build_task_management_routes

    return build_task_management_routes()


def _build_default_read_model_routes() -> ReadModelRoutes:
    from agentkit.backend.bootstrap.composition_root import build_project_read_model_routes

    return build_project_read_model_routes()
