"""CP10c handler: ARE scope-map validation."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agentkit.backend.core_types.mcp_server_registration import ARE_MCP_SERVER
from agentkit.backend.installer.bootstrap_checkpoints.cp10_checkpoint_support import (
    planned_or_status,
    skipped_result,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10_mcp_registration import (
    _load_target_mcp_json,
    _target_mcp_json_path,
)
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.context import (
    ScopeInteractionMode,
)
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_ALREADY_SATISFIED,
    REASON_ARE_DISABLED,
    REASON_MCP_CONFIGURATION_INVALID,
    REASON_PENDING_SELECTION,
)
from agentkit.backend.installer.checkpoint_engine.result_builder import (
    is_dry_run,
    make_result,
    planned_result,
)
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from agentkit.backend.installer.checkpoint_engine.context import (
        CheckpointContext,
    )
    from agentkit.backend.installer.registration import CheckpointResult

REASON_ARE_MCP_MISSING = "are_mcp_server_missing"


def cp10c_are_scope_validation(
    context: CheckpointContext,
) -> CheckpointResult:
    """Validate ARE scope mapping after the CP10 ARE-MCP precondition."""
    start = time.monotonic()
    if not context.are_enabled:
        return skipped_result(
            nid.CP_10C_ARE_SCOPE_VALIDATION,
            context,
            detail="features.are disabled; ARE-scope validation not applicable.",
            reason=REASON_ARE_DISABLED,
            start=start,
        )
    are_registered, mcp_config_error = _are_mcp_registered(context)
    if mcp_config_error is not None:
        return make_result(
            nid.CP_10C_ARE_SCOPE_VALIDATION,
            status=CheckpointStatus.FAILED,
            detail=(
                "Target .mcp.json is invalid; CP 10c cannot verify the "
                f"ARE-MCP precondition: {mcp_config_error}."
            ),
            reason=REASON_MCP_CONFIGURATION_INVALID,
            start=start,
        )
    if not are_registered:
        return make_result(
            nid.CP_10C_ARE_SCOPE_VALIDATION,
            status=CheckpointStatus.FAILED,
            detail=(
                "ARE-MCP server is not registered in the target .mcp.json; "
                "CP 10c requires the CP 10 ARE-MCP registration."
            ),
            reason=REASON_ARE_MCP_MISSING,
            start=start,
        )
    unmapped = _unmapped_are_items(context)
    if unmapped:
        return _unmapped_result(context, unmapped=unmapped, start=start)
    return _mapped_result(context, start=start)


def _unmapped_result(
    context: CheckpointContext,
    *,
    unmapped: set[str],
    start: float,
) -> CheckpointResult:
    if context.scope_interaction_mode == ScopeInteractionMode.AGENTIC:
        detail = (
            "PENDING_SELECTION: unmapped ARE items require selection: "
            f"{sorted(unmapped)}. The orchestrating agent must call "
            "resolve_pending_scope_mapping()."
        )
        if is_dry_run(context.mode):
            return planned_result(
                nid.CP_10C_ARE_SCOPE_VALIDATION,
                planned_status=CheckpointStatus.SKIPPED,
                detail=detail,
                skip_reason=REASON_PENDING_SELECTION,
                start=start,
            )
        return make_result(
            nid.CP_10C_ARE_SCOPE_VALIDATION,
            status=CheckpointStatus.SKIPPED,
            detail=detail,
            reason=REASON_PENDING_SELECTION,
            start=start,
        )
    return planned_or_status(
        nid.CP_10C_ARE_SCOPE_VALIDATION,
        context,
        mutate_status=CheckpointStatus.UPDATED,
        detail=f"Interactive ARE-scope selection required for {sorted(unmapped)}.",
        start=start,
    )


def _mapped_result(
    context: CheckpointContext,
    *,
    start: float,
) -> CheckpointResult:
    detail = "All ARE code repos carry are_scope and all modules are mapped."
    if context.run_state.resolved_scope_mappings:
        resolved_detail = (
            detail
            + " Resolved this run: "
            + f"{sorted(context.run_state.resolved_scope_mappings)}."
        )
        return planned_or_status(
            nid.CP_10C_ARE_SCOPE_VALIDATION,
            context,
            mutate_status=CheckpointStatus.UPDATED,
            detail=resolved_detail,
            start=start,
        )
    if context.mode.mutations_allowed:
        return make_result(
            nid.CP_10C_ARE_SCOPE_VALIDATION,
            status=CheckpointStatus.SKIPPED,
            detail=detail + " Idempotent re-run; nothing to map.",
            reason=REASON_ALREADY_SATISFIED,
            start=start,
        )
    if is_dry_run(context.mode):
        return planned_result(
            nid.CP_10C_ARE_SCOPE_VALIDATION,
            planned_status=CheckpointStatus.PASS,
            detail=detail,
            start=start,
        )
    return make_result(
        nid.CP_10C_ARE_SCOPE_VALIDATION,
        status=CheckpointStatus.PASS,
        detail=detail,
        start=start,
    )


def _are_mcp_registered(
    context: CheckpointContext,
) -> tuple[bool, str | None]:
    mcp_path = _target_mcp_json_path(context.project_root)
    if not mcp_path.is_file():
        if not context.mode.mutations_allowed:
            return context.are_enabled, None
        return False, None
    loaded, load_error = _load_target_mcp_json(mcp_path)
    if load_error is not None:
        return False, load_error
    assert loaded is not None
    servers = loaded.get("mcpServers")
    return isinstance(servers, dict) and ARE_MCP_SERVER in servers, None


def _unmapped_are_items(context: CheckpointContext) -> set[str]:
    yaml_data = context.run_state.project_yaml or {}
    are = yaml_data.get("are")
    are_map = are.get("module_scope_map") if isinstance(are, dict) else None
    mapped: set[str] = set(are_map) if isinstance(are_map, dict) else set()
    repositories = yaml_data.get("repositories")
    unmapped: set[str] = set()
    if not isinstance(repositories, list):
        return unmapped
    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        scope = repo.get("are_scope")
        name = str(repo.get("name", ""))
        if not scope:
            unmapped.add(name or "<unnamed-repo>")
        elif str(scope) not in mapped:
            unmapped.add(str(scope))
    return unmapped


__all__ = ["REASON_ARE_MCP_MISSING", "cp10c_are_scope_validation"]
