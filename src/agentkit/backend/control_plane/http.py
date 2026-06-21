"""Compat re-export: control_plane.http -> control_plane_http (AG3-090).

``control_plane_http`` is the canonical import-owner of the App/Router-Registry
(FK-72 §72.8.2).  This module is a SINGLE backwards-compat re-export so that
existing callers that import ``agentkit.backend.control_plane.http`` continue to resolve
the SAME classes — no second definition, no parallel transport (SINGLE SOURCE OF
TRUTH / FIX THE MODEL).

Import from ``agentkit.backend.control_plane_http`` in new code.
"""

from __future__ import annotations

from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    ControlPlaneApplicationRoutes,
    HttpResponse,
    serve_control_plane,
)
from agentkit.backend.control_plane_http.tenant_scope import TenantScopeMiddleware

__all__ = [
    "ControlPlaneApplication",
    "ControlPlaneApplicationRoutes",
    "HttpResponse",
    "TenantScopeMiddleware",
    "serve_control_plane",
]
