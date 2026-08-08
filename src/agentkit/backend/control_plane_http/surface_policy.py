"""Per-request admission policy of the two control-plane listeners (FK-72 §72.8.2).

One writer process serves two HTTPS surfaces, and the security question they
answer is not the routing question ``app.py`` answers: *which principal, on
which listener, may reach which route at all*. That decision is owned here --
the surface enum, the per-surface route sets, the auth/tenant middleware chain
and the surface gate itself -- so the routing module keeps only the dispatch of
routes it has already admitted.

Extracted from ``app.py`` (AG3-229) as a pure structural move; the names, the
patterns and the order of the checks are unchanged.
"""

from __future__ import annotations

import re
from enum import Enum
from http import HTTPStatus
from typing import TYPE_CHECKING

from agentkit.backend.auth.middleware import AuthMiddlewareResponse
from agentkit.backend.control_plane_http.responses import (
    HttpResponse,
    _auth_middleware_response_to_http_response,
    _error_response,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from agentkit.backend.auth.middleware import AuthMiddleware, AuthResult
    from agentkit.backend.control_plane_http.tenant_scope import TenantScopeMiddleware


class ControlPlaneSurface(Enum):
    """Security context of one listener in the shared writer process."""

    UI_BFF = "ui-bff"
    PROJECT_API = "project-api"


_UI_ONLY_ROUTE_PATTERNS = (
    re.compile(r"^/v1/projects/[^/]+/(?:dashboard|planning)(?:/|$)"),
    re.compile(r"^/v1/governance/takeover-approvals(?:/|$)"),
)
_PROJECT_ONLY_ROUTE_PATTERNS = (
    re.compile(r"^/v1/project-edge(?:/|$)"),
    re.compile(r"^/v1/projects/[^/]+/installation(?:/|$)"),
    re.compile(r"^/v1/telemetry/events(?:/|$)"),
    re.compile(r"^/v1/governance/(?:guard-counters|worker-health)(?:/|$)"),
    # AG3-241: the verify-system surface is an edge-facing project-token path.
    # The UI never assesses a conflict and never assembles evidence.
    re.compile(
        r"^/v1/projects/[^/]+/(?:story-conflict-assessments"
        r"|verify-evidence-assemblies)$"
    ),
)
_PROJECT_STRATEGIST_ADMIN_ROUTE_PATTERNS = (
    re.compile(r"^/v1/auth/(?:login|logout|password)$"),
    re.compile(r"^/v1/projects/[^/]+/api-tokens(?:/[^/]+)?$"),
    re.compile(r"^/v1/projects/[^/]+/installation/third-party-validation$"),
    re.compile(
        r"^/v1/project-edge/story-runs/[^/]+/ownership/"
        r"(?:takeover-(?:request|confirm|deny|reconcile-clear|reconcile-worktree)|recover)$",
    ),
    re.compile(r"^/v1/project-edge/operations/[^/]+/admin-abort$"),
    re.compile(r"^/v1/projects/[^/]+/stories/[^/]+/(?:split|reset|exit)$"),
    re.compile(r"^/v1/projects/[^/]+/failure-corpus(?:/|$)"),
)
_PROJECT_SCOPED_PATH_PATTERN = re.compile(r"^/v1/projects/([^/]+)/(.+)$")

_PROJECT_CONTEXT_BOOTSTRAP_PATH = "/v1/projects"
_PRINCIPAL_FORBIDDEN_CODE = "listener_principal_forbidden"
_ROUTE_NOT_EXPOSED_MESSAGE = (
    "This route is not exposed on the selected control-plane listener"
)


def _is_project_scoped_path(route_path: str) -> bool:
    """Return True for paths that carry a project_key as a path segment.

    Project-scoped paths follow /v1/projects/{key}/<something> (not just
    /v1/projects or /v1/projects/{key} which are the project_management
    special surface).
    """
    match = _PROJECT_SCOPED_PATH_PATTERN.match(route_path)
    return match is not None


def _run_request_middleware(
    *,
    auth_middleware: AuthMiddleware | None,
    tenant_scope: TenantScopeMiddleware,
    method: str,
    route_path: str,
    request_headers: Mapping[str, str] | None,
    correlation_id: str,
) -> tuple[HttpResponse | None, AuthResult | None]:
    """Run auth and tenant middleware; return any short-circuit plus auth context."""
    authorized: AuthResult | None = None
    if auth_middleware is not None:
        auth_result = auth_middleware.authorize(
            method=method,
            route_path=route_path,
            request_headers=request_headers,
            correlation_id=correlation_id,
        )
        if isinstance(auth_result, AuthMiddlewareResponse):
            return _auth_middleware_response_to_http_response(auth_result), None
        authorized = auth_result

    # Tenant-scope middleware validates project resources only. Non-project
    # endpoints (/healthz, auth, concepts, hub, project-edge) bypass it.
    if _is_project_scoped_path(route_path):
        tenant_result = tenant_scope.validate(
            method=method,
            route_path=route_path,
            correlation_id=correlation_id,
        )
        if isinstance(tenant_result, HttpResponse):
            return tenant_result, authorized
    return None, authorized


def _enforce_surface_policy(
    *,
    surface: ControlPlaneSurface | None,
    method: str,
    route_path: str,
    auth_result: AuthResult | None,
    correlation_id: str,
) -> HttpResponse | None:
    """Enforce listener-specific principal and route rights inside one process."""

    if surface is None:
        return None
    if surface is ControlPlaneSurface.UI_BFF:
        return _enforce_ui_bff_policy(
            method=method,
            route_path=route_path,
            auth_result=auth_result,
            correlation_id=correlation_id,
        )
    return _enforce_project_api_policy(
        method=method,
        route_path=route_path,
        auth_result=auth_result,
        correlation_id=correlation_id,
    )


def _enforce_ui_bff_policy(
    *,
    method: str,
    route_path: str,
    auth_result: AuthResult | None,
    correlation_id: str,
) -> HttpResponse | None:
    """The UI-BFF listener serves human sessions and no machine principal."""
    if auth_result is not None and auth_result.auth_kind == "project_api_token":
        return _error_response(
            HTTPStatus.FORBIDDEN,
            error_code=_PRINCIPAL_FORBIDDEN_CODE,
            message="Project API tokens are not accepted by the UI-BFF listener",
            correlation_id=correlation_id,
        )
    if _is_project_context_bootstrap(method, route_path):
        return _error_response(
            HTTPStatus.NOT_FOUND,
            error_code="listener_route_not_exposed",
            message="The credential-less project bootstrap is exposed only on "
            "the Project-API listener",
            correlation_id=correlation_id,
        )
    return _blocked_route_response(
        route_path,
        _PROJECT_ONLY_ROUTE_PATTERNS,
        correlation_id,
    )


def _enforce_project_api_policy(
    *,
    method: str,
    route_path: str,
    auth_result: AuthResult | None,
    correlation_id: str,
) -> HttpResponse | None:
    """The Project-API listener serves machines, and strategists only for admin."""
    blocked = _blocked_route_response(
        route_path,
        _UI_ONLY_ROUTE_PATTERNS,
        correlation_id,
    )
    if blocked is not None:
        return blocked
    project_context_bootstrap = _is_project_context_bootstrap(method, route_path)
    if (
        project_context_bootstrap
        and auth_result is not None
        and auth_result.auth_kind == "project_api_token"
    ):
        return _error_response(
            HTTPStatus.FORBIDDEN,
            error_code=_PRINCIPAL_FORBIDDEN_CODE,
            message="Project API tokens cannot create the credential-less project "
            "context reserved for strategist bootstrap",
            correlation_id=correlation_id,
        )
    if _is_non_administrative_strategist_route(
        auth_result,
        route_path,
        project_context_bootstrap=project_context_bootstrap,
    ):
        return _error_response(
            HTTPStatus.FORBIDDEN,
            error_code=_PRINCIPAL_FORBIDDEN_CODE,
            message="Strategist sessions are accepted by Project-API only on "
            "explicit administrative routes",
            correlation_id=correlation_id,
        )
    return None


def _is_project_context_bootstrap(method: str, route_path: str) -> bool:
    """Return whether the request creates the credential-less project context."""
    return method == "POST" and route_path == _PROJECT_CONTEXT_BOOTSTRAP_PATH


def _blocked_route_response(
    route_path: str,
    patterns: tuple[re.Pattern[str], ...],
    correlation_id: str,
) -> HttpResponse | None:
    """Hide a route that the OTHER listener owns behind a 404, never a 403."""
    if not any(pattern.match(route_path) is not None for pattern in patterns):
        return None
    return _error_response(
        HTTPStatus.NOT_FOUND,
        error_code="listener_route_not_exposed",
        message=_ROUTE_NOT_EXPOSED_MESSAGE,
        correlation_id=correlation_id,
    )


def _is_non_administrative_strategist_route(
    auth_result: AuthResult | None,
    route_path: str,
    *,
    project_context_bootstrap: bool,
) -> bool:
    """Return whether a strategist session reaches beyond its Project-API exception."""
    if auth_result is None or auth_result.auth_kind != "strategist_session":
        return False
    if project_context_bootstrap:
        return False
    return not any(
        pattern.match(route_path) is not None
        for pattern in _PROJECT_STRATEGIST_ADMIN_ROUTE_PATTERNS
    )
