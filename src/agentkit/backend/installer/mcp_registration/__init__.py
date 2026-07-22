"""MCP dual-harness registration helpers (AG3-175 / FK-50 §50.3 CP 10).

Coordinates a single rendered, digest-bound :class:`McpServerSpec` into Claude
Code ``.mcp.json`` and Codex ``.codex/config.toml`` without re-derivation.
"""

from __future__ import annotations

from agentkit.backend.installer.mcp_registration.bound_spec import (
    BoundMcpServerRegistration,
    ProbeBindingError,
    bind_after_probe,
    canonical_spec_digest,
    project_spec_to_claude_entry,
    project_spec_to_codex_entry,
    require_probe_binding,
    spec_to_conformance_command,
)
from agentkit.backend.installer.mcp_registration.dual_write import (
    DualRegistrationPlan,
    DualWriteResult,
    apply_dual_registration_writes,
    build_story_kb_spec,
    prepare_dual_registration,
)

__all__ = [
    "BoundMcpServerRegistration",
    "DualRegistrationPlan",
    "DualWriteResult",
    "ProbeBindingError",
    "apply_dual_registration_writes",
    "bind_after_probe",
    "build_story_kb_spec",
    "canonical_spec_digest",
    "prepare_dual_registration",
    "project_spec_to_claude_entry",
    "project_spec_to_codex_entry",
    "require_probe_binding",
    "spec_to_conformance_command",
]
