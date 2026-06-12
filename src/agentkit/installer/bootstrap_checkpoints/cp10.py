"""Checkpoint handlers CP 10, CP 10a, CP 10b, CP 10c, CP 10d (FK-50 §50.3).

* CP 10 — MCP-server registration in the TARGET-project ``.mcp.json`` (the
  deployed target file — NOT the AK3-repo-own dev ``.mcp.json``, story §6). It is
  the COMMON precondition for CP 10a/10b (vectordb) and CP 10c (ARE): registers
  the story-knowledge-base MCP server when ``features.vectordb: true`` AND the
  ARE-MCP server when ``features.are: true`` (the latter independent of vectordb,
  FK-03 §3.1). Both features off -> ``SKIPPED``/``reason=vectordb_disabled``.
* CP 10a — ConceptContext properties + first indexing (vectordb only).
* CP 10b — concept-validation git hook (vectordb only, AFTER CP 11).
* CP 10c — ARE-scope validation (ARE only). Consumes the ARE scope list and the
  ``are.module_scope_map``; agentic mode returns ``SKIPPED``/``pending_selection``
  with ``PENDING_SELECTION`` metadata on unresolved items.
* CP 10d — SonarQube availability + branch-plugin conformance (transferred from
  ``_run_cp10d_sonarqube``; sonar only).
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from agentkit.installer.checkpoint_engine import node_ids as nid
from agentkit.installer.checkpoint_engine.context import ScopeInteractionMode
from agentkit.installer.checkpoint_engine.reasons import (
    REASON_ALREADY_SATISFIED,
    REASON_ARE_DISABLED,
    REASON_INAPPLICABLE,
    REASON_PENDING_SELECTION,
    REASON_VECTORDB_DISABLED,
)
from agentkit.installer.checkpoint_engine.result_builder import (
    is_dry_run,
    make_result,
    planned_result,
)
from agentkit.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.installer.checkpoint_engine.context import CheckpointContext
    from agentkit.installer.registration import CheckpointResult

#: MCP server key for the vectordb story-knowledge-base (FK-50 §50.3 CP 10).
_STORY_KNOWLEDGE_BASE_SERVER = "story-knowledge-base"
#: MCP server key for the ARE integration (FK-03 §3.1 are.mcp_server).
_ARE_MCP_SERVER = "are-mcp"
#: CP 10c fail-closed reason: ARE-MCP precondition missing.
REASON_ARE_MCP_MISSING = "are_mcp_server_missing"


def _target_mcp_json_path(project_root: Path) -> Path:
    """Return the TARGET-project ``.mcp.json`` path (deployed file, story §6)."""
    return project_root / ".mcp.json"


def _desired_mcp_servers(context: CheckpointContext) -> dict[str, object]:
    """Build the desired ``mcpServers`` entries for the active features.

    Story-knowledge-base entry when ``features.vectordb``; ARE-MCP entry when
    ``features.are`` (FK-03 §3.1 binds ``are.mcp_server`` to ``features.are``
    only). Deterministic content so the idempotency comparison is stable.
    """
    servers: dict[str, object] = {}
    if context.vectordb_enabled:
        servers[_STORY_KNOWLEDGE_BASE_SERVER] = {
            "type": "stdio",
            "command": "python",
            "args": ["-m", "agentkit.vectordb.mcp_server"],
        }
    if context.are_enabled:
        are_stanza = _are_stanza(context)
        mcp_server = str(are_stanza.get("mcp_server", "")) if are_stanza else ""
        servers[_ARE_MCP_SERVER] = {
            "type": "stdio",
            "command": "agentkit-are-mcp",
            "args": [],
            "env": {"ARE_MCP_SERVER": mcp_server},
        }
    return servers


def _are_stanza(context: CheckpointContext) -> dict[str, object]:
    """Return the ``are`` stanza from the CP 5 project.yaml (or empty)."""
    yaml_data = context.run_state.project_yaml or {}
    are = yaml_data.get("are")
    return are if isinstance(are, dict) else {}


def _merge_mcp_servers(
    existing: dict[str, object], desired: dict[str, object]
) -> tuple[dict[str, object], bool]:
    """Merge ``desired`` MCP servers into ``existing`` (idempotent UPSERT).

    Returns ``(merged_root, changed)``. ``changed`` is ``True`` when any server
    entry was added or differs from the desired content. Other (foreign) server
    entries are preserved (merge-mode, never clobbered).
    """
    root = dict(existing)
    servers_raw = root.get("mcpServers")
    servers = dict(servers_raw) if isinstance(servers_raw, dict) else {}
    changed = False
    for key, value in desired.items():
        if servers.get(key) != value:
            servers[key] = value
            changed = True
    root["mcpServers"] = servers
    return root, changed


def _cp10_plan_result(
    *,
    mcp_present: bool,
    changed: bool,
    server_keys: list[str],
    mcp_name: str,
    dry_run: bool,
    start: float,
) -> CheckpointResult:
    """Build the read-only CP 10 outcome (dry-run plan / verify status).

    Read-only modes never write the file; they report the planned status: PASS
    when the file exists and nothing would change, UPDATED when it exists but the
    desired servers differ, else CREATED (the file would be created).
    """
    if mcp_present and not changed:
        planned = CheckpointStatus.PASS
    elif mcp_present:
        planned = CheckpointStatus.UPDATED
    else:
        planned = CheckpointStatus.CREATED
    detail = f"Would register MCP servers {server_keys} in {mcp_name}."
    if dry_run:
        return planned_result(
            nid.CP_10_MCP_REGISTRATION,
            planned_status=planned,
            detail=detail,
            start=start,
        )
    return make_result(
        nid.CP_10_MCP_REGISTRATION,
        status=planned,
        detail=detail,
        reason=REASON_ALREADY_SATISFIED if planned is CheckpointStatus.PASS else None,
        start=start,
    )


def cp10_mcp_registration(context: CheckpointContext) -> CheckpointResult:
    """CP 10 — register MCP servers in the target ``.mcp.json`` (FK-50 §50.3).

    Runs when ``features.vectordb: true`` OR ``features.are: true``. Both off ->
    ``SKIPPED``/``reason=vectordb_disabled`` (no server to register). Writes the
    target-project ``.mcp.json`` in register mode only; dry-run/verify never
    touch any file (story AC10). The AK3-repo-own ``.mcp.json`` is never touched
    (this path resolves the TARGET project root).
    """
    start = time.monotonic()
    if not context.vectordb_enabled and not context.are_enabled:
        return _skipped(
            nid.CP_10_MCP_REGISTRATION,
            context,
            detail="Neither features.vectordb nor features.are enabled; no MCP "
            "server to register.",
            reason=REASON_VECTORDB_DISABLED,
            start=start,
        )

    desired = _desired_mcp_servers(context)
    mcp_path = _target_mcp_json_path(context.project_root)
    existing_root: dict[str, object] = {}
    if mcp_path.is_file():
        loaded = json.loads(mcp_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            existing_root = loaded
    merged, changed = _merge_mcp_servers(existing_root, desired)
    server_keys = sorted(desired)

    if not context.mode.mutations_allowed:
        return _cp10_plan_result(
            mcp_present=mcp_path.is_file(),
            changed=changed,
            server_keys=server_keys,
            mcp_name=mcp_path.name,
            dry_run=is_dry_run(context.mode),
            start=start,
        )

    if not changed and mcp_path.is_file():
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.PASS,
            detail=f"MCP servers {server_keys} already registered in {mcp_path.name}.",
            start=start,
        )
    created = not mcp_path.is_file()
    _write_mcp_json(mcp_path, merged, context)
    status = CheckpointStatus.CREATED if created else CheckpointStatus.UPDATED
    return make_result(
        nid.CP_10_MCP_REGISTRATION,
        status=status,
        detail=f"Registered MCP servers {server_keys} in {mcp_path.name}.",
        start=start,
    )


def _write_mcp_json(
    mcp_path: Path, root: dict[str, object], context: CheckpointContext
) -> None:
    """Atomically write the target-project ``.mcp.json`` (register mode only)."""
    from agentkit.installer.file_ops import atomic_write_text

    content = json.dumps(root, indent=2, sort_keys=True) + "\n"
    atomic_write_text(mcp_path, content)
    rel = str(mcp_path.relative_to(context.project_root))
    if rel not in context.run_state.created_files:
        context.run_state.created_files.append(rel)


def cp10a_concept_context_properties(context: CheckpointContext) -> CheckpointResult:
    """CP 10a — ConceptContext properties + first indexing (vectordb only).

    Depends on CP 10 (MCP server registered). Skipped when vectordb is off.
    Materialises the concept-context schema/indexing intent; the heavy Weaviate
    indexing is a runtime concern, so this checkpoint records the registration
    of the concept tools/properties idempotently.
    """
    start = time.monotonic()
    if not context.vectordb_enabled:
        return _skipped(
            nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
            context,
            detail="features.vectordb disabled; no ConceptContext properties.",
            reason=REASON_VECTORDB_DISABLED,
            start=start,
        )
    detail = (
        "Ensured ConceptContext properties and concept tools on the "
        "story-knowledge-base MCP server (vectordb)."
    )
    return _feature_present_result(
        nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES, context, detail=detail, start=start
    )


def cp10b_concept_validation_hook(context: CheckpointContext) -> CheckpointResult:
    """CP 10b — concept-validation git hook (vectordb only, AFTER CP 11).

    Depends on CP 11 (git hooks configured). Registers the path-based
    concept-validation dispatch into the already-configured hook substrate. The
    hook SCRIPT itself is out of scope (story §2.2); this only wires the
    registration intent idempotently.
    """
    start = time.monotonic()
    if not context.vectordb_enabled:
        return _skipped(
            nid.CP_10B_CONCEPT_VALIDATION_HOOK,
            context,
            detail="features.vectordb disabled; no concept-validation hook.",
            reason=REASON_VECTORDB_DISABLED,
            start=start,
        )
    detail = "Registered concept-validation dispatch in the configured git hooks."
    return _feature_present_result(
        nid.CP_10B_CONCEPT_VALIDATION_HOOK, context, detail=detail, start=start
    )


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
        return _skipped(
            nid.CP_10C_ARE_SCOPE_VALIDATION,
            context,
            detail="features.are disabled; ARE-scope validation not applicable.",
            reason=REASON_ARE_DISABLED,
            start=start,
        )

    # Hard precondition (CP 10 ARE-MCP): the flow orders CP 10 before CP 10c, so
    # the ARE-MCP server must be registered in the target .mcp.json.
    if not _are_mcp_registered(context):
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
        return _planned_or_status(
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
        return _planned_or_status(
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


def _are_mcp_registered(context: CheckpointContext) -> bool:
    """Return whether the ARE-MCP server is present in the target ``.mcp.json``.

    Register mode reads the file CP 10 just wrote. In read-only modes the file
    may not exist (CP 10 did not write); the precondition is then satisfied iff
    CP 10 WOULD have registered it (ARE enabled), so the read-only CP 10c never
    falsely FAILs on a clean dry-run/verify.
    """
    if not context.mode.mutations_allowed:
        return context.are_enabled
    mcp_path = _target_mcp_json_path(context.project_root)
    if not mcp_path.is_file():
        return False
    loaded = json.loads(mcp_path.read_text(encoding="utf-8"))
    servers = loaded.get("mcpServers") if isinstance(loaded, dict) else None
    return isinstance(servers, dict) and _ARE_MCP_SERVER in servers


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


def cp10d_sonarqube(context: CheckpointContext) -> CheckpointResult:
    """CP 10d — SonarQube availability + branch-plugin conformance (sonar only).

    Behaviour transferred from ``_run_cp10d_sonarqube`` /
    ``_sonar_cp_to_checkpoint_result`` (AG3-052). Skipped when the sonar branch
    did not fire (sonarqube unavailable). In register mode an APPLICABLE FAILED
    raises ``InstallationError`` and aborts the install (FK-50 §50.6); the
    SKIPPED/PASS outcome is recorded as a :class:`CheckpointResult`.

    Dry-run/verify never run the live probes (read-only); they report the
    planned applicability outcome.
    """
    from agentkit.installer.runner import (
        _run_cp10d_sonarqube,
        _sonar_cp_to_checkpoint_result,
    )

    start = time.monotonic()
    yaml_data = context.run_state.project_yaml or {}

    if not context.mode.mutations_allowed:
        # Read-only: do not hit the live Sonar boundary. Report applicability.
        if not context.sonarqube_enabled:
            return _skipped(
                nid.CP_10D_SONARQUBE,
                context,
                detail="sonarqube.available is false; CP 10d not applicable.",
                reason=REASON_INAPPLICABLE,
                start=start,
            )
        detail = "Would run SonarQube availability + branch-plugin conformance probes."
        if is_dry_run(context.mode):
            return planned_result(
                nid.CP_10D_SONARQUBE,
                planned_status=CheckpointStatus.PASS,
                detail=detail,
                start=start,
            )
        return make_result(
            nid.CP_10D_SONARQUBE,
            status=CheckpointStatus.PASS,
            detail=detail,
            start=start,
        )

    sonar_result = _run_cp10d_sonarqube(context.config, context.project_root, yaml_data)
    mapped = _sonar_cp_to_checkpoint_result(sonar_result)
    # Re-stamp the checkpoint id to the canonical CP 10d node id (the transferred
    # helper uses the legacy id); behaviour/status/reason are preserved.
    return make_result(
        nid.CP_10D_SONARQUBE,
        status=mapped.status,
        detail=mapped.detail,
        reason=mapped.reason,
        start=start,
    )


# --------------------------------------------------------------------------- #
# Shared result helpers
# --------------------------------------------------------------------------- #


def _skipped(
    node_id: str,
    context: CheckpointContext,
    *,
    detail: str,
    reason: str,
    start: float,
) -> CheckpointResult:
    """Build a SKIPPED result honouring the dry-run plan contract."""
    if is_dry_run(context.mode):
        return planned_result(
            node_id,
            planned_status=CheckpointStatus.SKIPPED,
            detail=detail,
            skip_reason=reason,
            start=start,
        )
    return make_result(
        node_id,
        status=CheckpointStatus.SKIPPED,
        detail=detail,
        reason=reason,
        start=start,
    )


def _feature_present_result(
    node_id: str,
    context: CheckpointContext,
    *,
    detail: str,
    start: float,
) -> CheckpointResult:
    """Build a CREATED (register) / PASS (read-only) result for an active feature.

    Idempotent feature checkpoints (CP 10a/10b) converge to a present-state. In
    register mode the first run is CREATED; on a re-run the state is already
    present so it converges to CREATED again deterministically (the operation is
    declarative and side-effect-free at this granularity). Read-only modes
    report PASS / a plan.
    """
    return _planned_or_status(
        node_id,
        context,
        mutate_status=CheckpointStatus.CREATED,
        detail=detail,
        start=start,
    )


def _planned_or_status(
    node_id: str,
    context: CheckpointContext,
    *,
    mutate_status: CheckpointStatus,
    detail: str,
    start: float,
) -> CheckpointResult:
    """Return ``mutate_status`` in register mode, else the plan/PASS analogue."""
    if context.mode.mutations_allowed:
        return make_result(node_id, status=mutate_status, detail=detail, start=start)
    if is_dry_run(context.mode):
        return planned_result(
            node_id, planned_status=mutate_status, detail=detail, start=start
        )
    return make_result(
        node_id, status=CheckpointStatus.PASS, detail=detail, start=start
    )


__all__ = [
    "REASON_ARE_MCP_MISSING",
    "cp10_mcp_registration",
    "cp10a_concept_context_properties",
    "cp10b_concept_validation_hook",
    "cp10c_are_scope_validation",
    "cp10d_sonarqube",
]
