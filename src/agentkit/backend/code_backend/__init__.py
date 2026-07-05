"""Code-backend BC: provider-neutral capability port (FK-12 §12.1, AG3-146).

The public surface is the minimal :class:`CodeBackendPort` capability set plus
its typed result forms. Provider adapters (e.g.
:class:`agentkit.integration_clients.github.adapter.GitHubCodeBackendAdapter`)
implement the Protocol; consumers depend on this module only, never on a
concrete adapter (PO-Direktive III, Azure-DevOps-Tauglichkeit).
"""

from __future__ import annotations

from agentkit.backend.code_backend.provider_port import (
    CodeBackendCapability,
    CodeBackendPort,
    CompareEvidenceResult,
    RefReadResult,
    RepoProbeResult,
)

__all__ = [
    "CodeBackendCapability",
    "CodeBackendPort",
    "CompareEvidenceResult",
    "RefReadResult",
    "RepoProbeResult",
]
