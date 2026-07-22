"""CP 10 family package surface (AG3-176 R14 — thin re-export).

Handlers and dual-harness MCP implementation live in:

* ``cp10_mcp`` — CP10 registration + dual write/conformance/preflight
* ``cp10a_first_index`` — first indexing
* ``cp10b_hooks`` — concept git hooks
* ``cp10c_are`` — ARE scope
* ``cp10d_sonar`` — Sonar/third-party

This module re-exports the public handlers (registry surface) and the
``cp10_mcp`` symbols that unit/contract tests historically monkeypatch via
``bootstrap_checkpoints.cp10``.
"""

from __future__ import annotations

from agentkit.backend.installer.bootstrap_checkpoints.cp10_mcp import (
    REASON_ARE_MCP_MISSING,
    cp10_mcp_registration,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10a_first_index import (
    cp10a_concept_context_properties,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10b_hooks import (
    cp10b_concept_validation_hook,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10c_are import (
    cp10c_are_scope_validation,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10d_sonar import (
    cp10d_sonarqube,
)

__all__ = [
    "REASON_ARE_MCP_MISSING",
    "cp10_mcp_registration",
    "cp10a_concept_context_properties",
    "cp10b_concept_validation_hook",
    "cp10c_are_scope_validation",
    "cp10d_sonarqube",
]
