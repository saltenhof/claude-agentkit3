"""CP10 handler: MCP registration in both target-project harnesses.

CP10 registers servers in the TARGET-project ``.mcp.json`` (the
  deployed target file — NOT the AK3-repo-own dev ``.mcp.json``, story §6). It is
  the COMMON precondition for CP 10a/10b and CP 10c (ARE): always registers
  the mandatory story-knowledge-base MCP server and additionally registers the
  ARE-MCP server when ``features.are: true`` (FK-03 §3.1).
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

from agentkit.backend.core_types.mcp_server_registration import (
    AK3_SERVER_SHAPES,
    ARE_MCP_SERVER,
    ARE_MCP_SERVER_ENV_KEY,
    ARE_MCP_WRAPPER_NAME,
    STORY_KNOWLEDGE_BASE_SERVER,
    DesiredMcpServer,
    McpServerRegistrationError,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp10_checkpoint_support import (
    record_created_file as _record_created_file,
)
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_ALREADY_SATISFIED,
    REASON_CONFIGURATION_INVALID,
    REASON_MCP_COMMAND_NOT_FOUND,
    REASON_MCP_CONFIGURATION_INVALID,
    REASON_REGISTRATION_INCOMPLETE,
)
from agentkit.backend.installer.checkpoint_engine.result_builder import (
    is_dry_run,
    make_result,
    planned_result,
)
from agentkit.backend.installer.codex_settings import (
    read_codex_config_bytes,
    render_project_codex_config,
    write_codex_config_text,
)
from agentkit.backend.installer.interpreter import (
    InterpreterResolutionError,
    resolve_ak3_wrapper,
)
from agentkit.backend.installer.mcp_registration import (
    STORY_KNOWLEDGE_BASE_ARGS,
    ProbedRegistration,
    RegistrationBeforeImage,
    RenderedRegistration,
    assert_cwd_is_project_root,
    build_registration_env,
    desired_server_from_spec,
    probe_registration,
    render_mcp_json_text,
    resolve_story_knowledge_base_command,
    verify_interpreter_serves_ak3,
)
from agentkit.backend.installer.paths import (
    CODEX_CONFIG_FILE,
    CODEX_DIR,
    codex_config_path,
)
from agentkit.backend.installer.registration import CheckpointStatus
from agentkit.backend.installer.strict_json import (
    contains_lone_surrogate,
    contains_non_finite_float,
    exceeds_max_json_nesting,
    reject_duplicate_object_pairs,
    reject_non_json_constant,
)
from agentkit.backend.utils.io import atomic_write_text
from agentkit.backend.vectordb.project_binding import (
    ProjectBindingError,
    resolve_authoritative_project_id,
)
from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
from agentkit.harness_client.harness_adapters.codex_config_toml import CodexConfigError

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.config.models import ProjectConfig
    from agentkit.backend.installer.checkpoint_engine.context import CheckpointContext
    from agentkit.backend.installer.registration import CheckpointResult

def _target_mcp_json_path(project_root: Path) -> Path:
    """Return the TARGET-project ``.mcp.json`` path (deployed file, story §6)."""
    return project_root / ".mcp.json"


def _load_target_mcp_json_bytes(
    raw: bytes | None,
) -> tuple[dict[str, object] | None, str | None]:
    """Strict-load the target ``.mcp.json`` from ALREADY-CAPTURED bytes.

    Separated from the path-reading wrapper so a caller that must bind a
    before-image can parse and render from the *same* bytes it bound. Reading the
    file twice — once to parse, once for the before-image — allowed a concurrent
    foreign edit to bind a NEWER before-image to a STALER rendering, which made the
    pre-write guard authorise exactly the stale overwrite it exists to prevent.

    Args:
        raw: The file's bytes, or ``None`` when the file does not exist.

    Returns:
        Same contract as :func:`_load_target_mcp_json`.
    """
    if raw is None:
        return {}, None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, f"target .mcp.json is not valid UTF-8: {exc}"
    return _parse_target_mcp_json(text)


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
    return _parse_target_mcp_json(text)


def _parse_target_mcp_json(
    text: str,
) -> tuple[dict[str, object] | None, str | None]:
    """Strict-parse already-decoded ``.mcp.json`` text (shared by both loaders)."""
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
        return None, (f"target .mcp.json root must be a JSON object; got {type(loaded).__name__}")
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
            return None, (f"target .mcp.json key 'mcpServers' must be a JSON object; got {type(servers).__name__}")
        for name, entry in servers.items():
            if not isinstance(entry, dict):
                return None, (f"target .mcp.json server entry {name!r} must be a JSON object; got {type(entry).__name__}")
    return {str(k): v for k, v in loaded.items()}, None


def _desired_mcp_servers(
    context: CheckpointContext,
) -> tuple[DesiredMcpServer, ...]:
    """Build the typed desired MCP registrations for the active features.

    Mandatory story-knowledge-base; ARE-MCP additionally when ``features.are``
    (FK-03 §3.1 binds ``are.mcp_server`` to ``features.are`` only). Deterministic
    content, sorted by name, so the idempotency comparison and the registration
    digest are stable.

    The story-knowledge-base entry is built from ONE ``McpServerSpec`` produced by
    ``RuntimeBinding.from_env`` — the FK-13 SSOT — so the probed, the written and
    (per AG3-174) the consumed spec are the same object.

    Raises:
        McpServerRegistrationError: When the consumed configuration cannot
            produce a complete registration (caller reports a named FAILED).
        ProjectBindingError: When no authoritative project id can be derived.
    """
    servers: list[DesiredMcpServer] = [_story_knowledge_base_server(context)]
    if context.are_enabled:
        are_stanza = _are_stanza(context)
        mcp_server = str(are_stanza.get("mcp_server", "")) if are_stanza else ""
        servers.append(
            DesiredMcpServer(
                name=ARE_MCP_SERVER,
                command=str(resolve_ak3_wrapper(ARE_MCP_WRAPPER_NAME)),
                args=AK3_SERVER_SHAPES[ARE_MCP_SERVER].args,
                cwd=str(context.project_root),
                env=((ARE_MCP_SERVER_ENV_KEY, mcp_server),),
            )
        )
    return tuple(sorted(servers, key=lambda item: item.name))


def _project_config(context: CheckpointContext) -> ProjectConfig:
    """Return the CP-5-produced project configuration, strictly typed.

    CP 5 publishes the mapping on the run-state in EVERY mode
    (``cp01_to_06.py`` sets it before the mode branch), so this works for
    ``register`` as well as the read-only modes where the file is not on disk yet.
    Validating it through :class:`ProjectConfig` keeps ONE typed configuration
    truth instead of digging in a raw dict.

    Raises:
        McpServerRegistrationError: When CP 5 has not run or the mapping is not a
            valid project configuration.
    """
    candidate = context.run_state.project_config
    if candidate is None:
        raise McpServerRegistrationError(
            "CP 5 has not published a project configuration; CP 10 cannot derive the MCP registration (fail-closed precondition)."
        )
    return candidate


def _story_knowledge_base_server(context: CheckpointContext) -> DesiredMcpServer:
    """Build the story-knowledge-base registration from the typed configuration.

    Sources (all typed, no environment access for configuration values):

    * ``PROJECT_ID`` — ``resolve_authoritative_project_id`` (the FK-13 SSOT
      resolver; the CP-5 ``project_prefix`` is the authority, a divergent
      ``PROJECT_ID`` in the installing shell is a hard error).
    * both Weaviate endpoints — ``pipeline.vectordb``; absent is a named FAILED,
      never a synthesised default (PO decision D2).
    * ``AGENTKIT_CONCEPTS_DIR`` / ``AGENTKIT_STORIES_DIR`` — the configured
      ``concepts_dir`` / ``wiki_stories_dir``, made ABSOLUTE against the project
      root. Absolute on purpose: the entry point resolves a relative value against
      the process ``cwd``, and ``cwd`` must not become a second configuration
      source (D2).

    Raises:
        McpServerRegistrationError: On any missing/invalid configuration value.
    """
    project_config = _project_config(context)
    vectordb = project_config.pipeline.vectordb
    http_endpoint = vectordb.weaviate_http_endpoint if vectordb else None
    grpc_endpoint = vectordb.weaviate_grpc_endpoint if vectordb else None
    if not http_endpoint or not grpc_endpoint:
        raise McpServerRegistrationError(
            "features.vectordb is enabled but pipeline.vectordb does not declare "
            "both weaviate_http_endpoint and weaviate_grpc_endpoint; the MCP "
            "server would refuse its own runtime binding. No endpoint is ever "
            "synthesised (fail-closed, PO decision D2)."
        )
    project_id = resolve_authoritative_project_id(
        project_root=str(context.project_root),
        supplied=None,
        env=os.environ,
        config_project_id=project_config.project_prefix,
    )
    env = build_registration_env(
        project_id=project_id,
        weaviate_http_endpoint=http_endpoint,
        weaviate_grpc_endpoint=grpc_endpoint,
        concepts_dir=_absolute_within_root(context.project_root, project_config.concepts_dir),
        stories_dir=_absolute_within_root(context.project_root, project_config.wiki_stories_dir),
    )
    # The registered command is the ABSOLUTE interpreter that provides AK3, and
    # it is proven able to import the MCP entrypoint BEFORE anything is written.
    # A bare "python" would hand the choice to the harness process' PATH, which
    # generally resolves to an interpreter without AK3's dependencies.
    command = resolve_story_knowledge_base_command()
    verify_interpreter_serves_ak3(command)
    binding = RuntimeBinding.from_env(
        env,
        command=command,
        args=STORY_KNOWLEDGE_BASE_ARGS,
        cwd=str(context.project_root),
    )
    return desired_server_from_spec(STORY_KNOWLEDGE_BASE_SERVER, binding.spec)


def _absolute_within_root(project_root: Path, configured: str) -> str:
    """Return ``configured`` as an absolute path proven to stay inside the root.

    ``ProjectConfig`` already rejects absolute, drive-anchored and ``..``-bearing
    layout directories (``_validate_project_relative_dir``); this adds the
    resolved containment proof so a corpus root can never point outside the
    project (same discipline as the Codex path guard).

    Raises:
        McpServerRegistrationError: On a containment violation.
    """
    root = project_root.resolve()
    resolved = (root / configured).resolve()
    if not resolved.is_relative_to(root):
        raise McpServerRegistrationError(
            f"configured directory {configured!r} resolves to {resolved}, outside "
            f"the project root {root} (containment violation, fail-closed)."
        )
    return str(resolved)


def _are_stanza(context: CheckpointContext) -> dict[str, object]:
    """Return the ``are`` stanza from the CP 5 project.yaml (or empty)."""
    yaml_data = context.run_state.project_yaml or {}
    are = yaml_data.get("are")
    return are if isinstance(are, dict) else {}


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

    VectorDB is a mandatory capability, so the story-knowledge-base server is
    always registered. ARE remains an independent optional addition.

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
    # Phase 1 — derive ONE registration from the typed configuration.
    try:
        desired = _desired_mcp_servers(context)
    except InterpreterResolutionError as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail="ARE MCP command cannot be resolved through the central AK3 "
            f"interpreter owner: {exc} No file was written.",
            reason=REASON_MCP_COMMAND_NOT_FOUND,
            start=start,
        )
    except (McpServerRegistrationError, ProjectBindingError) as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=f"MCP registration cannot be derived from the project configuration: {exc} No file was written.",
            reason=REASON_CONFIGURATION_INVALID,
            start=start,
        )
    server_keys = [server.name for server in desired]
    mcp_path = _target_mcp_json_path(context.project_root)

    # Phase 2/3 — read BOTH before-images, conflict-check BOTH, render BOTH.
    try:
        rendered, changed = _render_both(context, desired)
    except _RegistrationRejectedError as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=exc.detail,
            reason=exc.reason,
            start=start,
        )

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

    # Phase 4 — live conformance. It runs BEFORE the idempotency verdict, not
    # after: FK-50 §50.3 CP 10 defines the idempotent outcome as "bereits
    # identische Eintraege -> PASS (Conformance erneut bestanden)", i.e. the PASS
    # ASSERTS a passed handshake. Returning PASS on a byte-identical registration
    # without probing would report a server that has stopped working as fine.
    # Read-only modes returned above, so no process starts in DRY_RUN/VERIFY.
    registration_probe = context.config.mcp_registration_probe or probe_registration
    probed, conformance_failure = registration_probe(rendered)
    if conformance_failure is not None:
        reason, detail = conformance_failure
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=detail,
            reason=reason,
            start=start,
        )
    assert probed is not None  # conformance_failure is None ⇒ receipt present

    # Phase 5 — idempotency: both files already carry the rendered content AND the
    # conformance check just passed again.
    if not changed:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.PASS,
            detail=(
                f"MCP servers {server_keys} already registered in "
                f"{mcp_path.name} and {CODEX_DIR}/{CODEX_CONFIG_FILE}; "
                "conformance re-verified."
            ),
            reason=REASON_ALREADY_SATISFIED,
            start=start,
        )

    # Phases 6-9 — verify the binding, then write both files.
    return _commit_registration(context, probed, server_keys=server_keys, mcp_path=mcp_path, start=start)


class _RegistrationRejectedError(Exception):
    """Internal signal: a pre-write rejection with its CP 10 reason."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _render_both(
    context: CheckpointContext,
    desired: tuple[DesiredMcpServer, ...],
) -> tuple[RenderedRegistration, bool]:
    """Read, conflict-check and fully render BOTH harness files (D6 phases 2-3).

    Nothing is written here. Any rejection raises :class:`_RegistrationRejectedError`,
    so a parse or conflict error in EITHER file yields zero writes — which is why
    the reads and renders both happen before the first write rather than
    interleaved with it.

    Returns:
        ``(rendered, changed)`` where ``changed`` is ``True`` when at least one of
        the two files would differ from its before-image.
    """
    # Containment invariant BEFORE anything is probed or written (AC 5).
    try:
        assert_cwd_is_project_root(desired, context.project_root)
    except McpServerRegistrationError as exc:
        raise _RegistrationRejectedError(REASON_CONFIGURATION_INVALID, f"{exc} No file was written.") from exc
    mcp_path = _target_mcp_json_path(context.project_root)

    # ONE read per file. Parsing, rendering and the bound before-image all derive
    # from exactly these bytes. Reading twice let a concurrent foreign edit bind a
    # NEWER before-image to a STALER rendering, after which the pre-write guard
    # found before-image and disk in agreement and authorised the stale overwrite
    # it exists to prevent — losing the foreign change silently.
    try:
        mcp_before = mcp_path.read_bytes() if mcp_path.is_file() else None
    except OSError as exc:
        raise _RegistrationRejectedError(
            REASON_CONFIGURATION_INVALID,
            f"Target .mcp.json cannot be read: {exc}. No file was written.",
        ) from exc
    existing_root, load_error = _load_target_mcp_json_bytes(mcp_before)
    if load_error is not None:
        raise _RegistrationRejectedError(
            REASON_MCP_CONFIGURATION_INVALID,
            f"Target .mcp.json is invalid; refusing registration without mutation: {load_error}. No file was written.",
        )
    assert existing_root is not None  # load_error is None ⇒ root is a dict

    try:
        codex_before = read_codex_config_bytes(context.project_root)
        codex_text = render_project_codex_config(context.project_root, desired, raw=codex_before)
    except CodexConfigError as exc:
        raise _RegistrationRejectedError(
            REASON_MCP_CONFIGURATION_INVALID,
            f"Target {CODEX_DIR}/{CODEX_CONFIG_FILE} is invalid ({exc.code}): {exc}. No file was written.",
        ) from exc
    except OSError as exc:
        raise _RegistrationRejectedError(
            REASON_CONFIGURATION_INVALID,
            f"Target {CODEX_DIR}/{CODEX_CONFIG_FILE} cannot be read: {exc}. No file was written.",
        ) from exc

    try:
        mcp_text, _ = render_mcp_json_text(existing_root, desired)
    except TypeError as exc:  # non-object mcpServers after a strict load
        raise _RegistrationRejectedError(
            REASON_MCP_CONFIGURATION_INVALID,
            f"Target .mcp.json cannot be merged: {exc}. No file was written.",
        ) from exc
    except McpServerRegistrationError as exc:  # AK3 name foreign-occupied
        raise _RegistrationRejectedError(
            REASON_MCP_CONFIGURATION_INVALID,
            f"{exc} No file was written.",
        ) from exc

    rendered = RenderedRegistration(
        servers=desired,
        mcp_json_text=mcp_text,
        codex_toml_text=codex_text,
        before_image=RegistrationBeforeImage(mcp_json=mcp_before, codex_config=codex_before),
    )
    changed = mcp_before != mcp_text.encode("utf-8") or codex_before != codex_text.encode("utf-8")
    return rendered, changed


def _commit_registration(
    context: CheckpointContext,
    probed: ProbedRegistration,
    *,
    server_keys: list[str],
    mcp_path: Path,
    start: float,
) -> CheckpointResult:
    """Verify the probe binding, then write both files with honest rollback.

    There is NO shared filesystem transaction across the two files. Each single
    write is atomic (temp + fsync + ``os.replace``), but not the pair. The crash
    window between them is documented, never sold as atomicity: a retry re-reads,
    re-renders deterministically and converges.
    """
    rendered = probed.rendered
    try:
        probed.verify_binding()
    except McpServerRegistrationError as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=f"{exc} No file was written.",
            reason=REASON_CONFIGURATION_INVALID,
            start=start,
        )

    # Concurrent-modification guard: both files must still match the bound
    # before-image, otherwise another writer changed them since phase 2 and the
    # rendered content is stale. A read failure here (ACL change, share lock) is a
    # NAMED result, not a raw exception out of the checkpoint engine.
    try:
        current_mcp = mcp_path.read_bytes() if mcp_path.is_file() else None
    except OSError as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=f"Target .mcp.json cannot be re-read before the write: {exc}. No file was written.",
            reason=REASON_CONFIGURATION_INVALID,
            start=start,
        )
    try:
        current_codex = read_codex_config_bytes(context.project_root)
    except CodexConfigError as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=f"{exc} No file was written.",
            reason=REASON_MCP_CONFIGURATION_INVALID,
            start=start,
        )
    except OSError as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=f"Target {CODEX_DIR}/{CODEX_CONFIG_FILE} cannot be re-read before the write: {exc}. No file was written.",
            reason=REASON_CONFIGURATION_INVALID,
            start=start,
        )
    if current_mcp != rendered.before_image.mcp_json or current_codex != rendered.before_image.codex_config:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=(
                "A harness configuration changed between the strict read and the "
                "write; the rendered registration is stale. No file was written."
            ),
            reason=REASON_MCP_CONFIGURATION_INVALID,
            start=start,
        )

    created = not mcp_path.is_file()
    try:
        _write_mcp_json_text(mcp_path, rendered.mcp_json_text, context)
    except OSError as exc:
        write_error = "".join(
            [
                f"Writing {mcp_path.name} failed: {exc}. No file was written; ",
                "the registration is incomplete and a retry converges.",
            ]
        )
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=write_error,
            reason=REASON_REGISTRATION_INCOMPLETE,
            start=start,
        )

    try:
        write_codex_config_text(context.project_root, rendered.codex_toml_text)
    except (OSError, CodexConfigError) as exc:
        rollback_note = _rollback_mcp_json(mcp_path, rendered.before_image.mcp_json)
        write_error = "".join(
            [
                f"Writing {CODEX_DIR}/{CODEX_CONFIG_FILE} failed: {exc}. ",
                f"{mcp_path.name} was already written; {rollback_note} ",
                "A repeated run converges idempotently.",
            ]
        )
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=write_error,
            reason=REASON_REGISTRATION_INCOMPLETE,
            start=start,
        )

    _record_created_file(context, mcp_path)
    _record_created_file(context, codex_config_path(context.project_root))
    status = CheckpointStatus.CREATED if created else CheckpointStatus.UPDATED
    return make_result(
        nid.CP_10_MCP_REGISTRATION,
        status=status,
        detail=f"Registered MCP servers {server_keys} in {mcp_path.name} and {CODEX_DIR}/{CODEX_CONFIG_FILE}.",
        start=start,
    )


def _rollback_mcp_json(mcp_path: Path, before: bytes | None) -> str:
    """Best-effort restore of ``.mcp.json`` from the BOUND before-image.

    Returns a human-readable note describing what actually happened. A clean
    rollback is never claimed when the restore itself failed — the same honesty
    line as ``runner._rollback_bindings``.
    """
    try:
        if before is None:
            if mcp_path.is_file():
                mcp_path.unlink()
            return "rolled back: the file did not exist before and was removed."
        mcp_path.write_bytes(before)
    except OSError as rollback_exc:
        return "".join(
            [
                f"ROLLBACK FAILED ({rollback_exc}); {mcp_path.name} is left in its ",
                "newly written state and must be reconciled by a repeated run.",
            ]
        )
    return "rolled back to its previous content."


def _write_mcp_json_text(mcp_path: Path, content: str, context: CheckpointContext) -> None:
    """Atomically write the pre-rendered target ``.mcp.json`` content.

    The content is rendered in phase 3 (``mcp_registration.render_mcp_json_text``,
    ``allow_nan=False`` as defense in depth) so this function only performs the
    write. ``newline=""`` keeps the bytes on disk equal to the rendered text,
    which the idempotency comparison and the bound before-image both rely on.
    """
    del context  # kept for signature symmetry with the created-file recording
    atomic_write_text(mcp_path, content, newline="")


__all__ = ["cp10_mcp_registration"]
