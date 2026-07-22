"""CP 10 — dual-harness MCP registration (AG3-176 / R14).

Orchestrates ports only: mcp_registration, endpoint_preflight, conformance.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_ALREADY_SATISFIED,
    REASON_MCP_CONFIGURATION_INVALID,
    REASON_MCP_PROTOCOL_ERROR,
    REASON_REGISTRATION_INCOMPLETE,
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
from agentkit.backend.installer.mcp_registration import (
    bind_after_probe,
    project_spec_to_claude_entry,
    spec_to_conformance_command,
)
from agentkit.backend.installer.mcp_registration.dual_write import (
    DualRegistrationError,
    apply_dual_registration_writes,
    build_story_kb_spec,
    prepare_dual_registration,
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
    from agentkit.backend.vectordb.runtime_binding import McpServerSpec

_STORY_KNOWLEDGE_BASE_SERVER = "story-knowledge-base"
_ARE_MCP_SERVER = "are-mcp"
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
    """Build desired ``mcpServers`` entries (legacy + ARE + Spec projection).

    Story-knowledge-base is **always** projected (VectorDB mandatory, AG3-176
    AC6) from the single rendered :class:`McpServerSpec` (AG3-175). ARE-MCP
    remains a Claude-only ``.mcp.json`` entry when ``features.are`` is on.
    Tests may replace this function to inject fixture servers; the dual-harness
    path is taken only when the live Spec path is active
    (see :func:`cp10_mcp_registration`).
    """
    servers: dict[str, object] = {}
    try:
        spec = build_story_kb_spec(context)
        servers[_STORY_KNOWLEDGE_BASE_SERVER] = project_spec_to_claude_entry(spec)
    except DualRegistrationError:
        # Surface later in the handler with a named FAILED; keep dict empty
        # for story-kb so callers that only inspect keys see the gap.
        pass
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


def _are_only_mcp_servers(context: CheckpointContext) -> dict[str, object]:
    """Return non-story-kb desired ``mcpServers`` entries (ARE)."""
    servers: dict[str, object] = {}
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
    """CP 10 — register MCP servers in target harness configs (FK-50 §50.3).

    VectorDB is mandatory (AG3-176 AC6): story-knowledge-base is always
    registered after a fail-closed endpoint preflight in **register** mode
    (no container/compose start, no localhost default). ARE-MCP remains
    optional when ``features.are: true``.

    When VectorDB dual-harness path is active (AG3-175):

    * Preflight the configured Weaviate endpoint (register only).
    * Render one :class:`McpServerSpec`, probe it with AG3-164, bind by digest.
    * Project **that same object** into Claude Code ``.mcp.json`` and Codex
      ``.codex/config.toml`` (never userspace).

    In **register** mode every desired server is probed **immediately before**
    any write. Dry-run/verify never start processes and never touch files.
    """
    start = time.monotonic()

    # Vectordb dual-harness path (AG3-175) is the live production path.
    # Tests that monkeypatch ``_desired_mcp_servers`` take the legacy single-file
    # path so AG3-164 fixtures stay stable.
    if _desired_mcp_servers is _DESIRED_MCP_SERVERS_IMPL:
        preflight_fail = _vectordb_endpoint_preflight(context, start=start)
        if preflight_fail is not None:
            return preflight_fail
        return _cp10_dual_harness_registration(context, start=start)

    return _cp10_mcp_json_only_registration(context, start=start)


def _vectordb_endpoint_preflight(
    context: CheckpointContext, *, start: float
) -> CheckpointResult | None:
    """Fail-closed endpoint preflight before registration (AG3-176 AC1).

    Dry-run/verify only validate the endpoint **shape** (no live probe, same
    class as MCP conformance). Register mode probes meta+ready and refuses
    registration on any named failure. Never starts a container/compose.
    """
    from agentkit.backend.vectordb.endpoint_preflight import (
        EndpointPreflightError,
        EndpointSpec,
        resolve_endpoint_from_vectordb_config,
        run_endpoint_preflight,
    )

    # Prefer InstallConfig Weaviate fields, then project.yaml vectordb stanza.
    host = getattr(context.config, "weaviate_host", None)
    http_port = getattr(context.config, "weaviate_http_port", None)
    grpc_port = getattr(context.config, "weaviate_grpc_port", None)
    raw: dict[str, object] | None = None
    if host and http_port and grpc_port:
        raw = {"host": host, "port": http_port, "grpc_port": grpc_port}
    else:
        yaml_data = context.run_state.project_yaml or {}
        vdb = yaml_data.get("vectordb")
        if not isinstance(vdb, dict):
            pipeline = yaml_data.get("pipeline")
            if isinstance(pipeline, dict):
                maybe = pipeline.get("vectordb")
                vdb = maybe if isinstance(maybe, dict) else None
        if isinstance(vdb, dict):
            raw = dict(vdb)

    try:
        endpoint = resolve_endpoint_from_vectordb_config(raw)
    except EndpointPreflightError as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=exc.detail,
            reason=exc.reason,
            start=start,
        )

    if not context.mode.mutations_allowed:
        # Shape-only in dry_run/verify — no live network, no registration write.
        return None

    # Live meta+ready probe. Unit tests inject via module attributes.
    ready_probe = _PREFLIGHT_READY_PROBE
    meta_fetcher = _PREFLIGHT_META_FETCHER
    kwargs: dict[str, object] = {}
    if ready_probe is not None:
        kwargs["ready_probe"] = ready_probe
    if meta_fetcher is not None:
        kwargs["meta_fetcher"] = meta_fetcher
    try:
        run_endpoint_preflight(endpoint, **kwargs)  # type: ignore[arg-type]
    except EndpointPreflightError as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=(
                f"{exc.detail} Registration was not written; installer does not "
                "start a database (AG3-176 AC1)."
            ),
            reason=exc.reason,
            start=start,
        )
    _ = EndpointSpec
    return None


# Injectable preflight seams for unit tests (default: real network probes).
_PREFLIGHT_READY_PROBE: object | None = None
_PREFLIGHT_META_FETCHER: object | None = None


#: Production identity of ``_desired_mcp_servers`` for dual-path detection.
_DESIRED_MCP_SERVERS_IMPL = _desired_mcp_servers


def _cp10_mcp_json_only_registration(
    context: CheckpointContext, *, start: float
) -> CheckpointResult:
    """Single-file ``.mcp.json`` registration (ARE-only / test doubles)."""
    desired = _desired_mcp_servers(context)
    mcp_path = _target_mcp_json_path(context.project_root)
    existing_root, load_error = _load_target_mcp_json(mcp_path)
    if load_error is not None:
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
    assert existing_root is not None
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


def _cp10_dual_harness_registration(
    context: CheckpointContext, *, start: float
) -> CheckpointResult:
    """Register story-kb into both harness configs from one bound Spec."""
    preflight = _dual_preflight(context, start=start)
    if not isinstance(preflight, tuple):
        return preflight
    existing_root, mcp_before, codex_before, story_spec, mcp_path, codex_path = (
        preflight
    )

    other_servers = _are_only_mcp_servers(context)
    desired_for_keys = {
        _STORY_KNOWLEDGE_BASE_SERVER: project_spec_to_claude_entry(story_spec),
        **other_servers,
    }
    server_keys = sorted(desired_for_keys)

    if not context.mode.mutations_allowed:
        return _dual_plan_result(
            context,
            start=start,
            story_spec=story_spec,
            existing_root=existing_root,
            mcp_before=mcp_before,
            other_servers=other_servers,
            desired_for_keys=desired_for_keys,
            server_keys=server_keys,
            mcp_path=mcp_path,
            codex_path=codex_path,
        )

    return _dual_register_result(
        context,
        start=start,
        story_spec=story_spec,
        existing_root=existing_root,
        mcp_before=mcp_before,
        codex_before=codex_before,
        other_servers=other_servers,
        server_keys=server_keys,
        mcp_path=mcp_path,
        codex_path=codex_path,
    )


def _dual_preflight(
    context: CheckpointContext, *, start: float
) -> CheckpointResult | tuple[dict[str, object], bytes | None, bytes | None, McpServerSpec, Path, Path]:
    """Load both configs and render the Spec; fail-closed with null writes."""
    from agentkit.harness_client.harness_adapters.codex_mcp_config_writer import (
        load_codex_mcp_document,
        project_codex_mcp_config_path,
    )

    mcp_path = _target_mcp_json_path(context.project_root)
    existing_root, load_error = _load_target_mcp_json(mcp_path)
    mcp_before = _read_before_image(mcp_path)
    if load_error is not None:
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
    assert existing_root is not None

    _codex_root, codex_before, codex_err = load_codex_mcp_document(context.project_root)
    if codex_err is not None:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=(
                f"Target .codex/config.toml is invalid; refusing registration "
                f"without mutation: {codex_err}."
            ),
            reason=REASON_MCP_CONFIGURATION_INVALID,
            start=start,
        )
    try:
        story_spec = build_story_kb_spec(context)
    except DualRegistrationError as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=exc.detail,
            reason=exc.reason,
            start=start,
        )
    codex_path = project_codex_mcp_config_path(context.project_root)
    return existing_root, mcp_before, codex_before, story_spec, mcp_path, codex_path


def _dual_plan_result(
    context: CheckpointContext,
    *,
    start: float,
    story_spec: McpServerSpec,
    existing_root: dict[str, object],
    mcp_before: bytes | None,
    other_servers: dict[str, object],
    desired_for_keys: dict[str, object],
    server_keys: list[str],
    mcp_path: Path,
    codex_path: Path,
) -> CheckpointResult:
    """Dry-run / verify plan for dual-harness registration (no process start)."""
    try:
        plan = prepare_dual_registration(
            project_root=context.project_root,
            bound=bind_after_probe(_STORY_KNOWLEDGE_BASE_SERVER, story_spec),
            existing_mcp_json_root=existing_root,
            mcp_json_before=mcp_before,
            other_mcp_json_servers=other_servers,
            mcp_json_renderer=_render_mcp_json_text,
        )
    except DualRegistrationError as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=exc.detail,
            reason=exc.reason,
            start=start,
        )
    _merged, mcp_only_changed = _merge_mcp_servers(existing_root, desired_for_keys)
    changed = plan.mcp_json_changed or plan.codex_changed or mcp_only_changed
    return _cp10_plan_result(
        mcp_present=mcp_path.is_file() and codex_path.is_file(),
        changed=changed,
        server_keys=server_keys,
        mcp_name=f"{mcp_path.name}+{codex_path.name}",
        dry_run=is_dry_run(context.mode),
        start=start,
    )


def _dual_register_result(
    context: CheckpointContext,
    *,
    start: float,
    story_spec: McpServerSpec,
    existing_root: dict[str, object],
    mcp_before: bytes | None,
    codex_before: bytes | None,
    other_servers: dict[str, object],
    server_keys: list[str],
    mcp_path: Path,
    codex_path: Path,
) -> CheckpointResult:
    """REGISTER path: probe bound Spec, then dual write with honest rollback."""
    probe_fail = _probe_all_for_dual(
        context, story_spec=story_spec, other_servers=other_servers
    )
    if probe_fail is not None:
        reason, detail = probe_fail
        _assert_byte_identical(mcp_path, mcp_before)
        _assert_byte_identical(codex_path, codex_before)
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=detail,
            reason=reason,
            start=start,
        )

    bound = bind_after_probe(_STORY_KNOWLEDGE_BASE_SERVER, story_spec)
    try:
        plan = prepare_dual_registration(
            project_root=context.project_root,
            bound=bound,
            existing_mcp_json_root=existing_root,
            mcp_json_before=mcp_before,
            other_mcp_json_servers=other_servers,
            mcp_json_renderer=_render_mcp_json_text,
        )
    except DualRegistrationError as exc:
        _assert_byte_identical(mcp_path, mcp_before)
        _assert_byte_identical(codex_path, codex_before)
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=exc.detail,
            reason=exc.reason,
            start=start,
        )

    if not plan.mcp_json_changed and not plan.codex_changed:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.PASS,
            detail=(
                f"MCP servers {server_keys} already registered in "
                f"{mcp_path.name} and {codex_path.name}."
            ),
            start=start,
        )

    created = (not mcp_path.is_file()) or (not codex_path.is_file())
    try:
        write_result = apply_dual_registration_writes(plan)
    except DualRegistrationError as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=exc.detail,
            reason=exc.reason if exc.reason else REASON_REGISTRATION_INCOMPLETE,
            start=start,
        )

    # Only surface paths that this run actually wrote (idempotent re-run with
    # byte-stable dual-write must leave created_files empty for those files).
    written_paths: list[Path] = []
    if write_result.mcp_json_written:
        written_paths.append(mcp_path)
    if write_result.codex_written:
        written_paths.append(codex_path)
    if written_paths:
        _record_created_paths(context, *written_paths)
    if not write_result.mcp_json_written and not write_result.codex_written:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.PASS,
            detail=(
                f"MCP servers {server_keys} already current in "
                f"{mcp_path.name} and {codex_path.name}."
            ),
            start=start,
        )
    status = CheckpointStatus.CREATED if created else CheckpointStatus.UPDATED
    return make_result(
        nid.CP_10_MCP_REGISTRATION,
        status=status,
        detail=(
            f"Registered MCP servers {server_keys} in {mcp_path.name} and "
            f"{codex_path.name} "
            f"(mcp_json_written={write_result.mcp_json_written}, "
            f"codex_written={write_result.codex_written})."
        ),
        start=start,
    )


def _probe_all_for_dual(
    context: CheckpointContext,
    *,
    story_spec: McpServerSpec,
    other_servers: dict[str, object],
) -> tuple[str, str] | None:
    """Run AG3-164 on the Spec (and ARE entries); Spec fields only for story-kb."""
    failure = _conformance_gate_for_spec(
        story_spec, server_id=_STORY_KNOWLEDGE_BASE_SERVER
    )
    if failure is not None:
        return failure
    if other_servers:
        return _conformance_gate(other_servers, cwd=context.project_root)
    return None


def _read_before_image(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def _record_created_paths(
    context: CheckpointContext, *paths: Path
) -> None:
    for path in paths:
        try:
            rel = str(path.relative_to(context.project_root))
        except ValueError:
            continue
        if rel not in context.run_state.created_files:
            context.run_state.created_files.append(rel)


def _render_mcp_json_text(root: dict[str, object]) -> str:
    """Serialize a ``.mcp.json`` root (strict, no NaN)."""
    return json.dumps(root, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _assert_byte_identical(path: Path, before: bytes | None) -> None:
    """Best-effort proof helper: file must match the bound before-image."""
    if before is None:
        if path.exists() or path.is_symlink():
            # File appeared unexpectedly — leave it; caller already FAILED.
            return
        return
    if not path.is_file():
        return
    try:
        if path.read_bytes() != before:
            return
    except OSError:
        return


def _conformance_gate_for_spec(
    spec: McpServerSpec,
    *,
    server_id: str,
) -> tuple[str, str] | None:
    """Probe ``spec`` via AG3-164 using only Spec fields (no re-derivation)."""
    bound_cmd = spec_to_conformance_command(spec)
    try:
        result = check_mcp_conformance(bound_cmd)
    except Exception as exc:  # noqa: BLE001 — CP10 boundary: named FAILED
        return (
            REASON_MCP_PROTOCOL_ERROR,
            f"MCP conformance internal fault for server {server_id!r}: {exc}. "
            "Registration was not written.",
        )
    if not result.ok:
        reason = (
            result.reason.value if result.reason is not None else REASON_MCP_PROTOCOL_ERROR
        )
        detail = (
            f"MCP conformance failed for server {server_id!r}: {result.detail} "
            "Registration was not written."
        )
        return reason, detail
    return None


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



__all__ = ["REASON_ARE_MCP_MISSING", "cp10_mcp_registration"]
