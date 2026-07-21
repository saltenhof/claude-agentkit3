"""Stable machine-readable checkpoint reason tokens (FK-50 §50.4).

Every ``SKIPPED``/``FAILED`` :class:`~agentkit.backend.installer.registration.CheckpointResult`
MUST carry a stable ``reason`` token (FK-50 §50.4, enforced by the model
validator). Centralising the tokens here keeps them switchable and English
(ARCH-55) and prevents prose-string drift across handlers and tests.
"""

from __future__ import annotations

from typing import Final

#: Inapplicability is carried as ``SKIPPED``/``not_applicable`` (FK-50 §50.4 —
#: no separate status word). Used for reserved/feature-off non-applicability
#: where a more specific token does not apply (e.g. the CP 10d sonar branch when
#: ``sonarqube.available`` is false).
REASON_INAPPLICABLE: Final = "not_applicable"
#: CP 3/CP 4 reserved no-op nodes (number stability, FK-50 §50.3).
REASON_RESERVED: Final = "reserved"
#: CP 10/10a/10b skipped because neither vectordb nor (for CP 10) ARE is on.
REASON_VECTORDB_DISABLED: Final = "vectordb_disabled"
#: CP 10c skipped because ``features.are: false``.
REASON_ARE_DISABLED: Final = "are_disabled"
#: CP 10c agentic mode: at least one ARE scope mapping is unresolved. The
#: domain-level ``PENDING_SELECTION`` metadata travels in ``detail``/handler
#: payload (no status neologism — FK-50 §50.4, story §2.1.2).
REASON_PENDING_SELECTION: Final = "pending_selection"
#: Idempotent re-run: the checkpoint was already satisfied, nothing changed.
REASON_ALREADY_SATISFIED: Final = "already_satisfied"
#: Dry-run plan token: a planned ``CREATED``/``UPDATED`` that performed NO
#: mutation (FK-50 §50.2 dry-run result contract, story §2.1.3). Lets a consumer
#: tell "planned, not executed" from a real mutation result.
REASON_PLANNED_NO_MUTATION: Final = "planned_no_mutation"

# CP 10 MCP conformance failures (AG3-164 / FK-50 §50.3 CP 10). Configured but
# non-runnable servers are FAILED (not SKIPPED); SKIPPED remains only for
# feature-off / consciously-absent cases.
REASON_MCP_COMMAND_NOT_FOUND: Final = "mcp_command_not_found"
REASON_MCP_PROCESS_EXITED: Final = "mcp_process_exited"
REASON_MCP_TIMEOUT: Final = "mcp_timeout"
REASON_MCP_PROTOCOL_ERROR: Final = "mcp_protocol_error"
REASON_MCP_TOOLS_LIST_EMPTY: Final = "mcp_tools_list_empty"
#: CP 10: process-tree control plane failed (job/group create, assign, terminate).
REASON_MCP_PROCESS_CONTROL_ERROR: Final = "mcp_process_control_error"
#: CP 10: target-project ``.mcp.json`` is present but not strictly loadable or
#: has an invalid configuration shape (duplicate names, non-JSON constants,
#: non-object root / ``mcpServers``). Distinct from wire ``mcp_protocol_error``.
REASON_MCP_CONFIGURATION_INVALID: Final = "mcp_configuration_invalid"

#: ``detail`` plan marker prefix carried by every dry-run ``CheckpointResult``
#: (story §2.1.3) so a consumer can detect a plan result without re-deriving the
#: mode. Kept distinct from the ``reason`` token (which is absent on a planned
#: PASS/SKIP) so BOTH planned-mutation and planned-no-mutation outcomes are
#: marked.
DRY_RUN_PLAN_MARKER: Final = "[dry-run plan]"


__all__ = [
    "DRY_RUN_PLAN_MARKER",
    "REASON_ALREADY_SATISFIED",
    "REASON_ARE_DISABLED",
    "REASON_INAPPLICABLE",
    "REASON_MCP_COMMAND_NOT_FOUND",
    "REASON_MCP_CONFIGURATION_INVALID",
    "REASON_MCP_PROCESS_CONTROL_ERROR",
    "REASON_MCP_PROCESS_EXITED",
    "REASON_MCP_PROTOCOL_ERROR",
    "REASON_MCP_TIMEOUT",
    "REASON_MCP_TOOLS_LIST_EMPTY",
    "REASON_PENDING_SELECTION",
    "REASON_PLANNED_NO_MUTATION",
    "REASON_RESERVED",
    "REASON_VECTORDB_DISABLED",
]
