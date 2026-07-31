"""Compatibility alias for the split CP10 checkpoint family.

New production wiring imports each handler from its owning module. This alias
keeps older callers that patched CP10's MCP port seams attached to the real MCP
handler module instead of creating a second set of globals.
"""

from __future__ import annotations

import sys

from agentkit.backend.installer.bootstrap_checkpoints import (
    cp10_mcp_registration as _mcp_owner,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10a_initial_sync_checkpoint import (
    cp10a_concept_context_properties,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10b_hook_dispatch_checkpoint import (
    cp10b_concept_validation_hook,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10c_are_scope import (
    REASON_ARE_MCP_MISSING,
    cp10c_are_scope_validation,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10d_sonarqube import (
    cp10d_sonarqube,
)

_mcp_owner.cp10a_concept_context_properties = (  # type: ignore[attr-defined]
    cp10a_concept_context_properties
)
_mcp_owner.cp10b_concept_validation_hook = (  # type: ignore[attr-defined]
    cp10b_concept_validation_hook
)
_mcp_owner.cp10c_are_scope_validation = (  # type: ignore[attr-defined]
    cp10c_are_scope_validation
)
_mcp_owner.cp10d_sonarqube = cp10d_sonarqube  # type: ignore[attr-defined]
_mcp_owner.REASON_ARE_MCP_MISSING = REASON_ARE_MCP_MISSING  # type: ignore[attr-defined]
sys.modules[__name__] = _mcp_owner
