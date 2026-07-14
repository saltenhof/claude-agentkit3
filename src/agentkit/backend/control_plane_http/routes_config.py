"""Route dependency bundle for the control-plane HTTP application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:

    from agentkit.backend.auth.http.routes import AuthRoutes
    from agentkit.backend.concept_catalog.http.routes import ConceptCatalogRoutes
    from agentkit.backend.control_plane_http.permission_routes import PermissionRoutes
    from agentkit.backend.control_plane_http.takeover_approval_routes import TakeoverApprovalRoutes
    from agentkit.backend.execution_planning.http.routes import ExecutionPlanningRoutes
    from agentkit.backend.kpi_analytics.http.routes import KpiAnalyticsRoutes
    from agentkit.backend.project_management.http.routes import ProjectManagementRoutes
    from agentkit.backend.project_management.read_model_routes import ReadModelRoutes
    from agentkit.backend.story_context_manager.http.routes import StoryContextRoutes
    from agentkit.backend.task_management.http.routes import TaskManagementRoutes
    from agentkit.backend.telemetry.http.routes import TelemetryRoutes
    from agentkit.integration_clients.multi_llm_hub.http.routes import MultiLlmHubRoutes



# ---------------------------------------------------------------------------
# ControlPlaneApplicationRoutes — groups all BC-route dependencies (S107)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlPlaneApplicationRoutes:
    """Optional route-bundle for :class:`ControlPlaneApplication`.

    Collects all BC-route and middleware route overrides into a single
    typed object so that the constructor stays within the S107 parameter-count
    limit.  Every field defaults to ``None``; missing entries are filled with
    their respective ``_build_default_*`` helpers at construction time.
    """

    project_routes: ProjectManagementRoutes | None = None
    story_routes: StoryContextRoutes | None = None
    concept_routes: ConceptCatalogRoutes | None = None
    hub_routes: MultiLlmHubRoutes | None = None
    planning_routes: ExecutionPlanningRoutes | None = None
    telemetry_routes: TelemetryRoutes | None = None
    auth_routes: AuthRoutes | None = None
    kpi_analytics_routes: KpiAnalyticsRoutes | None = None
    read_model_routes: ReadModelRoutes | None = None
    task_management_routes: TaskManagementRoutes | None = None
    takeover_approval_routes: TakeoverApprovalRoutes | None = None
    permission_routes: PermissionRoutes | None = None
