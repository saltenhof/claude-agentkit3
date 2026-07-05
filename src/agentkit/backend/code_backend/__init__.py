"""Code-backend BC: provider-neutral capability port (FK-12 §12.1, AG3-146).

The public surface is the minimal :class:`CodeBackendPort` capability set plus
its typed result forms. Provider adapters (e.g.
:class:`agentkit.integration_clients.github.adapter.GitHubCodeBackendAdapter`)
implement the Protocol; consumers depend on this module only, never on a
concrete adapter (PO Directive III, Azure DevOps readiness).
"""

from __future__ import annotations

from agentkit.backend.code_backend.provider_port import (
    CodeBackendCapability,
    CodeBackendPort,
    CompareEvidenceResult,
    RefProtectionResult,
    RefReadResult,
    RepoProbeResult,
    StoryRefWriteCredentialClass,
    StoryRefWriteCredentialResult,
)

__all__ = [
    "CodeBackendCapability",
    "CodeBackendPort",
    "CompareEvidenceResult",
    "RefProtectionResult",
    "RefReadResult",
    "RepoProbeResult",
    "StoryRefWriteCredentialClass",
    "StoryRefWriteCredentialResult",
]
