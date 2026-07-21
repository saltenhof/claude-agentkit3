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

from agentkit.backend.exceptions import InstallationError
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.context import ScopeInteractionMode
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_ALREADY_SATISFIED,
    REASON_ARE_DISABLED,
    REASON_INAPPLICABLE,
    REASON_MCP_CONFIGURATION_INVALID,
    REASON_MCP_PROTOCOL_ERROR,
    REASON_PENDING_SELECTION,
    REASON_VECTORDB_DISABLED,
)
from agentkit.backend.installer.checkpoint_engine.result_builder import (
    is_dry_run,
    make_result,
    planned_result,
)
from agentkit.backend.installer.mcp_conformance import (
    McpServerCommand,
    check_mcp_conformance,
    server_command_from_mcp_entry,
)
from agentkit.backend.installer.registration import CheckpointStatus
from agentkit.backend.installer.strict_json import (
    contains_lone_surrogate,
    contains_non_finite_float,
    exceeds_max_json_nesting,
    reject_duplicate_object_pairs,
    reject_non_json_constant,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.installer.checkpoint_engine.context import CheckpointContext
    from agentkit.backend.installer.registration import CheckpointResult

#: MCP server key for the vectordb story-knowledge-base (FK-50 §50.3 CP 10).
_STORY_KNOWLEDGE_BASE_SERVER = "story-knowledge-base"
#: MCP server key for the ARE integration (FK-03 §3.1 are.mcp_server).
_ARE_MCP_SERVER = "are-mcp"
#: CP 10c fail-closed reason: ARE-MCP precondition missing.
REASON_ARE_MCP_MISSING = "are_mcp_server_missing"


def _target_mcp_json_path(project_root: Path) -> Path:
    """Return the TARGET-project ``.mcp.json`` path (deployed file, story §6)."""
    return project_root / ".mcp.json"


def _load_target_mcp_json(
    mcp_path: Path,
) -> tuple[dict[str, object] | None, str | None]:
    """Strict-load the target-project ``.mcp.json`` (fail-closed merge contract).

    Returns:
        ``({}, None)`` when the file is absent (empty root for merge).
        ``(root, None)`` when the file is present and structurally valid.
        ``(None, detail)`` when the file is present but invalid — caller must
        return named ``FAILED`` without mutation or conformance start.

    Rejects: invalid UTF-8, decoder recursion, excessive nesting (shared
    ceiling, iterative check — same class later serialisation would risk),
    duplicate object names at every level, non-JSON constants
    (``NaN``/``Infinity``/``-Infinity``), non-finite floats, lone UTF-16
    surrogates, a non-object root, a present ``mcpServers`` that is not a JSON
    object, and any ``mcpServers`` value that is not itself a JSON object.
    Does not silently last-wins or rewrite shape. ``MemoryError`` is not
    swallowed.
    """
    if not mcp_path.is_file():
        return {}, None
    try:
        text = mcp_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return None, f"target .mcp.json is not valid UTF-8: {exc}"
    except OSError as exc:
        return None, f"cannot read target .mcp.json: {exc}"
    try:
        loaded: object = json.loads(
            text,
            parse_constant=reject_non_json_constant,
            object_pairs_hook=reject_duplicate_object_pairs,
        )
    except json.JSONDecodeError as exc:
        return None, f"target .mcp.json is not strict JSON: {exc.msg}"
    except RecursionError:
        return None, "target .mcp.json nesting exceeds decoder limits"
    if not isinstance(loaded, dict):
        return None, (
            "target .mcp.json root must be a JSON object; "
            f"got {type(loaded).__name__}"
        )
    # Iterative post-decode checks — never RecursionError on mid-depth trees.
    if exceeds_max_json_nesting(loaded):
        return None, "target .mcp.json nesting exceeds validation limits"
    if contains_non_finite_float(loaded):
        return None, "target .mcp.json contains a non-finite JSON number"
    if contains_lone_surrogate(loaded):
        return None, "target .mcp.json contains a lone UTF-16 surrogate"
    if "mcpServers" in loaded:
        servers = loaded["mcpServers"]
        if not isinstance(servers, dict):
            return None, (
                "target .mcp.json key 'mcpServers' must be a JSON object; "
                f"got {type(servers).__name__}"
            )
        for name, entry in servers.items():
            if not isinstance(entry, dict):
                return None, (
                    f"target .mcp.json server entry {name!r} must be a JSON "
                    f"object; got {type(entry).__name__}"
                )
    return {str(k): v for k, v in loaded.items()}, None


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
            "args": ["-m", "agentkit.backend.vectordb.mcp_server"],
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
    # Callers must pass a root from ``_load_target_mcp_json``: when present,
    # ``mcpServers`` is a dict. Never silently replace a non-object value.
    if servers_raw is None:
        servers: dict[str, object] = {}
    elif isinstance(servers_raw, dict):
        servers = dict(servers_raw)
    else:
        msg = (
            "mcpServers must be a JSON object after strict load; "
            f"got {type(servers_raw).__name__}"
        )
        raise TypeError(msg)
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
    ``SKIPPED``/``reason=vectordb_disabled`` (no server to register).

    In **register** mode every desired server is probed with the generic MCP
    conformance check (process start, ``initialize``, non-empty ``tools/list``)
    **immediately before** any write. Failure is ``FAILED`` with a
    machine-readable reason; no partial write.

    Dry-run is pure plan derivation (no process start). Verify is read-only
    configuration shape / desired-vs-actual diff (no process start). An active
    MCP health probe in dry-run/verify is out of scope for AG3-164.

    Writes the target-project ``.mcp.json`` in register mode only; dry-run/verify
    never touch any file (story AC10). The AK3-repo-own ``.mcp.json`` is never
    touched (this path resolves the TARGET project root).
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
    existing_root, load_error = _load_target_mcp_json(mcp_path)
    if load_error is not None:
        # Invalid existing config: named FAILED in all modes, no mutation,
        # no conformance start (AC 8 merge contract / FAIL-CLOSED).
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=(
                f"Target .mcp.json is invalid; refusing registration without "
                f"mutation: {load_error}."
            ),
            reason=REASON_MCP_CONFIGURATION_INVALID,
            start=start,
        )
    assert existing_root is not None  # load_error is None ⇒ root is a dict
    merged, changed = _merge_mcp_servers(existing_root, desired)
    server_keys = sorted(desired)

    # Dry-run / verify: side-effect-free plan or status only (FK-50 §50.2).
    if not context.mode.mutations_allowed:
        return _cp10_plan_result(
            mcp_present=mcp_path.is_file(),
            changed=changed,
            server_keys=server_keys,
            mcp_name=mcp_path.name,
            dry_run=is_dry_run(context.mode),
            start=start,
        )

    # REGISTER only: live conformance immediately before any write.
    conformance_failure = _conformance_gate(desired, cwd=context.project_root)
    if conformance_failure is not None:
        reason, detail = conformance_failure
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=detail,
            reason=reason,
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


def _conformance_gate(
    desired: dict[str, object],
    *,
    cwd: Path,
) -> tuple[str, str] | None:
    """Run the generic MCP conformance check for every desired server entry.

    Returns ``(reason, detail)`` on the first failure; ``None`` when all
    servers pass. Never writes configuration. Order is sorted by server key
    for deterministic failure reporting.
    """
    for key in sorted(desired):
        entry = desired[key]
        if not isinstance(entry, dict):
            return (
                REASON_MCP_PROTOCOL_ERROR,
                f"MCP server entry {key!r} is not an object; refusing registration.",
            )
        try:
            cmd: McpServerCommand = server_command_from_mcp_entry(entry)
        except ValueError as exc:
            return (
                REASON_MCP_PROTOCOL_ERROR,
                f"MCP server entry {key!r} is invalid: {exc}",
            )
        # Bind cwd so relative module paths resolve against the target project.
        bound = McpServerCommand(
            command=cmd.command,
            args=cmd.args,
            env=cmd.env,
            cwd=cwd,
        )
        try:
            result = check_mcp_conformance(bound)
        except Exception as exc:  # noqa: BLE001 — CP10 boundary: named FAILED
            return (
                REASON_MCP_PROTOCOL_ERROR,
                f"MCP conformance internal fault for server {key!r}: {exc}. "
                "Registration was not written.",
            )
        if not result.ok:
            reason = (
                result.reason.value if result.reason is not None else REASON_MCP_PROTOCOL_ERROR
            )
            detail = (
                f"MCP conformance failed for server {key!r}: {result.detail} "
                "Registration was not written."
            )
            return reason, detail
    return None


def _write_mcp_json(
    mcp_path: Path, root: dict[str, object], context: CheckpointContext
) -> None:
    """Atomically write the target-project ``.mcp.json`` (register mode only).

    ``allow_nan=False`` is defense in depth: non-finite numbers must never be
    re-emitted into the target project configuration.
    """
    from agentkit.backend.installer.file_ops import atomic_write_text

    content = json.dumps(root, indent=2, sort_keys=True, allow_nan=False) + "\n"
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


def cp10d_sonarqube(context: CheckpointContext) -> CheckpointResult:
    """CP 10d — backend-mediated light Sonar/Jenkins/ARE validation.

    Behaviour transferred from ``_run_cp10d_sonarqube`` /
    ``_sonar_cp_to_checkpoint_result`` (AG3-052). Skipped when the sonar branch
    did not fire (sonarqube unavailable). In register mode an APPLICABLE FAILED
    raises ``InstallationError`` and aborts the install (FK-50 §50.6); the
    SKIPPED/PASS outcome is recorded as a :class:`CheckpointResult`.

    Dry-run reports a plan. Verify runs the same read-only live probes as
    register, but never starts the side-effecting conformance self-test.
    """
    from agentkit.backend.installer.runner import (
        _run_cp10d_sonarqube,
        _sonar_cp_to_checkpoint_result,
    )

    start = time.monotonic()
    yaml_data = context.run_state.project_yaml or {}

    if is_dry_run(context.mode):
        if not context.sonarqube_enabled:
            return _skipped(
                nid.CP_10D_SONARQUBE,
                context,
                detail="sonarqube.available is false; CP 10d not applicable.",
                reason=REASON_INAPPLICABLE,
                start=start,
            )
        detail = "Would request backend-owned light Sonar/Jenkins/ARE validation."
        return planned_result(
            nid.CP_10D_SONARQUBE,
            planned_status=CheckpointStatus.PASS,
            detail=detail,
            start=start,
        )

    if not context.sonarqube_enabled:
        return _skipped(
            nid.CP_10D_SONARQUBE,
            context,
            detail="No mediated third-party system is enabled; CP 10d not applicable.",
            reason=REASON_INAPPLICABLE,
            start=start,
        )

    try:
        sonar_result = _run_cp10d_sonarqube(
            context.config, context.project_root, yaml_data
        )
    except InstallationError as exc:
        if context.mode.mutations_allowed:
            raise
        error_code = str(exc.detail.get("error_code", "third_party_validation_failed"))
        raw_details = exc.detail.get("details")
        detail_items = raw_details if isinstance(raw_details, list) else [str(exc)]
        details = tuple(str(item) for item in detail_items)
        return make_result(
            nid.CP_10D_SONARQUBE,
            status=CheckpointStatus.FAILED,
            detail="; ".join(details),
            reason=error_code,
            start=start,
        )
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
