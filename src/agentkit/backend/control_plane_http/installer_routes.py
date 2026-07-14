"""Installer-related route dispatch shared by the control-plane application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.control_plane_http.responses import (
    HttpResponse,
    _project_response_to_http_response,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane_http.third_party_validation_routes import (
        ThirdPartyValidationRoutes,
    )
    from agentkit.backend.project_management.http.routes import ProjectManagementRoutes


class InstallerDispatchMixin:
    """Project registration and third-party installer route dispatch."""

    if TYPE_CHECKING:
        _project_routes: ProjectManagementRoutes
        _third_party_validation_routes: ThirdPartyValidationRoutes

    def _dispatch_installer_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> HttpResponse | None:
        """Dispatch project registration and installer mediation writes."""
        project_response = self._project_routes.handle_post(
            route_path, payload, correlation_id
        )
        if project_response is not None:
            return _project_response_to_http_response(project_response)
        return self._third_party_validation_routes.handle_post(
            route_path, payload, correlation_id
        )


__all__ = ["InstallerDispatchMixin"]
