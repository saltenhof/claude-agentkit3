"""CP 10c — ARE-scope validation (FK-50 / R14)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agentkit.backend.installer.bootstrap_checkpoints import cp10_mcp as _cp10_mcp
from agentkit.backend.installer.bootstrap_checkpoints.cp10_common import (
    planned_or_status,
    skipped,
)
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.context import ScopeInteractionMode
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

    from agentkit.backend.installer.checkpoint_engine.context import CheckpointContext
    from agentkit.backend.installer.registration import CheckpointResult

REASON_ARE_MCP_MISSING = "are_mcp_server_missing"
_ARE_MCP_SERVER = "are-mcp"


def cp10c_are_scope_validation(context: CheckpointContext) -> CheckpointResult:
    """CP 10c — ARE-scope validation (ARE only, FK-50 §50.3 CP 10c, story AC8).

    Depends on CP 5 (project config) + CP 10 (ARE-MCP registered). Skipped when
    ``features.are: false`` (``reason=are_disabled``). Otherwise:

    * Fail-closed FAILED when the ARE-MCP server is not registered (hard
      precondition from CP 10).
    * Validates ``are_scope`` on every code repo in ``repositories[]`` and that
      every module value has an ``are.module_scope_map`` entry; detects deltas
      (only new/unmapped items).
    * Agentic mode (default): unresolved mappings -> ``SKIPPED``/
      ``reason=pending_selection`` with ``PENDING_SELECTION`` metadata in
      ``detail`` (the orchestrating agent calls ``resolve_pending_scope_mapping``
      — a producer OUT of scope, story §2.2).
    * Mapping resolved/written DURING this run (``resolve_pending_scope_mapping``
      recorded entries on the run-state) -> ``UPDATED`` (register) / plan-UPDATED
      (dry_run) / ``PASS`` (verify).
    * Mapping already complete before this run -> idempotent ``SKIPPED``
      (register) / ``PASS`` (read-only). An idempotent re-run never re-claims an
      ``UPDATED`` (story AC8).
    """
    start = time.monotonic()
    if not context.are_enabled:
        return skipped(
            nid.CP_10C_ARE_SCOPE_VALIDATION,
            context,
            detail="features.are disabled; ARE-scope validation not applicable.",
            reason=REASON_ARE_DISABLED,
            start=start,
        )

    # Hard precondition (CP 10 ARE-MCP): the flow orders CP 10 before CP 10c, so
    # the ARE-MCP server must be registered in the target .mcp.json.
    are_registered, mcp_config_error = _are_mcp_registered(context)
    if mcp_config_error is not None:
        return make_result(
            nid.CP_10C_ARE_SCOPE_VALIDATION,
            status=CheckpointStatus.FAILED,
            detail=(
                "Target .mcp.json is invalid; CP 10c cannot verify the ARE-MCP "
                f"precondition: {mcp_config_error}."
            ),
            reason=REASON_MCP_CONFIGURATION_INVALID,
            start=start,
        )
    if not are_registered:
        return make_result(
            nid.CP_10C_ARE_SCOPE_VALIDATION,
            status=CheckpointStatus.FAILED,
            detail=(
                "ARE-MCP server is not registered in the target .mcp.json; CP 10c "
                "requires the CP 10 ARE-MCP registration (FK-50 §50.3 CP 10c)."
            ),
            reason=REASON_ARE_MCP_MISSING,
            start=start,
        )

    unmapped = _unmapped_are_items(context)
    if unmapped:
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
        # Interactive mode: a numbered-selection flow would resolve the items.
        # Headless installs use agentic mode; here we record the would-resolve.
        detail = f"Interactive ARE-scope selection required for {sorted(unmapped)}."
        return planned_or_status(
            nid.CP_10C_ARE_SCOPE_VALIDATION,
            context,
            mutate_status=CheckpointStatus.UPDATED,
            detail=detail,
            start=start,
        )

    # All items mapped. Distinguish "this run resolved/wrote the mapping"
    # (-> UPDATED) from "already complete, nothing changed" (-> SKIPPED/PASS),
    # so an idempotent re-run never falsely re-claims an UPDATED (story AC8).
    # ``resolve_pending_scope_mapping()`` (OUT of scope, story §2.2) records the
    # just-written entries on the run-state; their presence is the "resolved
    # this run" signal.
    resolved_this_run = bool(context.run_state.resolved_scope_mappings)
    detail = "All ARE code repos carry are_scope and all modules are mapped."

    if resolved_this_run:
        # The mapping was completed in THIS run (just resolved/written).
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

    # Already complete before this run: register -> idempotent skip; read-only
    # (dry_run/verify) -> PASS.
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
    """Return whether the ARE-MCP server is present in the target ``.mcp.json``.

    Returns ``(registered, config_error)``. ``config_error`` is set when the
    existing file fails the shared strict loader — callers must report
    ``mcp_configuration_invalid`` rather than ``are_mcp_server_missing``.

    When the file **exists**, every mode (REGISTER / DRY_RUN / VERIFY) uses
    ``_load_target_mcp_json`` so shape/parse failures surface as
    ``mcp_configuration_invalid``. When the file is **absent**, read-only modes
    derive the precondition from ``are_enabled`` (what CP 10 would register);
    register mode reports not registered.
    """
    mcp_path = _cp10_mcp._target_mcp_json_path(context.project_root)
    if not mcp_path.is_file():
        if not context.mode.mutations_allowed:
            return context.are_enabled, None
        return False, None
    loaded, load_error = _cp10_mcp._load_target_mcp_json(mcp_path)
    if load_error is not None:
        return False, load_error
    assert loaded is not None
    servers = loaded.get("mcpServers")
    registered = isinstance(servers, dict) and _ARE_MCP_SERVER in servers
    return registered, None


def _unmapped_are_items(context: CheckpointContext) -> set[str]:
    """Return ARE module values lacking an ``are.module_scope_map`` entry.

    Consumes (never defines) the ARE config: ``are.module_scope_map`` and the
    per-repo ``are_scope`` from the CP 5 project.yaml. A code repo without an
    ``are_scope`` and any module value not present as a key in
    ``module_scope_map`` is unmapped.
    """
    yaml_data = context.run_state.project_yaml or {}
    are = yaml_data.get("are")
    are_map = are.get("module_scope_map") if isinstance(are, dict) else None
    mapped: set[str] = set(are_map) if isinstance(are_map, dict) else set()

    repositories = yaml_data.get("repositories")
    unmapped: set[str] = set()
    if isinstance(repositories, list):
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
