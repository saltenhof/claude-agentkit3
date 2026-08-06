"""BFF-topology control-plane HTTP package (FK-72 §72.8.2, AG3-090).

``control_plane_http`` is the canonical import-owner of:
  - ``ControlPlaneApplication`` — the App / Router-Registry
  - ``serve_control_plane`` — the HTTPS server entry point
  - ``HttpResponse`` — the serializable HTTP response dataclass
  - ``TenantScopeMiddleware`` — project-key path extraction + validation

This package is the ONLY import path for these symbols. There is no second
namespace and no re-export facade (SINGLE SOURCE OF TRUTH, KEINE
KOMPATIBILITAETSSCHICHTEN).
"""

from agentkit.backend.control_plane_http.app import (
    ControlPlaneApplication,
    HttpResponse,
)
from agentkit.backend.control_plane_http.server import serve_control_plane
from agentkit.backend.control_plane_http.tenant_scope import TenantScopeMiddleware

__all__ = [
    "ControlPlaneApplication",
    "HttpResponse",
    "TenantScopeMiddleware",
    "serve_control_plane",
]
