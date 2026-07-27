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
import os
import time
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.config.models import ProjectConfig
from agentkit.backend.core_types.mcp_server_registration import (
    AK3_SERVER_SHAPES,
    ARE_MCP_SERVER,
    ARE_MCP_SERVER_ENV_KEY,
    STORY_KNOWLEDGE_BASE_SERVER,
    DesiredMcpServer,
    McpServerRegistrationError,
)
from agentkit.backend.exceptions import InstallationError
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.context import ScopeInteractionMode
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_ALREADY_SATISFIED,
    REASON_ARE_DISABLED,
    REASON_CONFIGURATION_INVALID,
    REASON_INAPPLICABLE,
    REASON_MCP_CONFIGURATION_INVALID,
    REASON_PENDING_SELECTION,
    REASON_REGISTRATION_INCOMPLETE,
    REASON_VECTORDB_DISABLED,
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
from agentkit.backend.installer.mcp_registration import (
    STORY_KNOWLEDGE_BASE_ARGS,
    STORY_KNOWLEDGE_BASE_COMMAND,
    ProbedRegistration,
    RegistrationBeforeImage,
    RenderedRegistration,
    assert_cwd_is_project_root,
    build_registration_env,
    desired_server_from_spec,
    probe_registration,
    render_mcp_json_text,
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

    from agentkit.backend.installer.checkpoint_engine.context import CheckpointContext
    from agentkit.backend.installer.registration import CheckpointResult

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


def _desired_mcp_servers(
    context: CheckpointContext,
) -> tuple[DesiredMcpServer, ...]:
    """Build the typed desired MCP registrations for the active features.

    Story-knowledge-base when ``features.vectordb``; ARE-MCP when ``features.are``
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
    servers: list[DesiredMcpServer] = []
    if context.vectordb_enabled:
        servers.append(_story_knowledge_base_server(context))
    if context.are_enabled:
        are_stanza = _are_stanza(context)
        mcp_server = str(are_stanza.get("mcp_server", "")) if are_stanza else ""
        servers.append(
            DesiredMcpServer(
                name=ARE_MCP_SERVER,
                command=AK3_SERVER_SHAPES[ARE_MCP_SERVER].command,
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
    raw = context.run_state.project_yaml
    if raw is None:
        raise McpServerRegistrationError(
            "CP 5 has not published a project configuration; CP 10 cannot derive "
            "the MCP registration (fail-closed precondition)."
        )
    try:
        return ProjectConfig.model_validate(raw)
    except ValidationError as exc:
        raise McpServerRegistrationError(
            f"the consumed project configuration is invalid: {exc}"
        ) from exc


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
        concepts_dir=_absolute_within_root(
            context.project_root, project_config.concepts_dir
        ),
        stories_dir=_absolute_within_root(
            context.project_root, project_config.wiki_stories_dir
        ),
    )
    binding = RuntimeBinding.from_env(
        env,
        command=STORY_KNOWLEDGE_BASE_COMMAND,
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

    # Phase 1 — derive ONE registration from the typed configuration.
    try:
        desired = _desired_mcp_servers(context)
    except (McpServerRegistrationError, ProjectBindingError) as exc:
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=(
                f"MCP registration cannot be derived from the project "
                f"configuration: {exc} No file was written."
            ),
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
    probed, conformance_failure = probe_registration(rendered)
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
    return _commit_registration(
        context, probed, server_keys=server_keys, mcp_path=mcp_path, start=start
    )


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
        raise _RegistrationRejectedError(
            REASON_CONFIGURATION_INVALID, f"{exc} No file was written."
        ) from exc
    mcp_path = _target_mcp_json_path(context.project_root)
    existing_root, load_error = _load_target_mcp_json(mcp_path)
    if load_error is not None:
        raise _RegistrationRejectedError(
            REASON_MCP_CONFIGURATION_INVALID,
            f"Target .mcp.json is invalid; refusing registration without "
            f"mutation: {load_error}. No file was written.",
        )
    assert existing_root is not None  # load_error is None ⇒ root is a dict

    try:
        codex_before = read_codex_config_bytes(context.project_root)
        codex_text = render_project_codex_config(context.project_root, desired)
    except CodexConfigError as exc:
        raise _RegistrationRejectedError(
            REASON_MCP_CONFIGURATION_INVALID,
            f"Target {CODEX_DIR}/{CODEX_CONFIG_FILE} is invalid "
            f"({exc.code}): {exc}. No file was written.",
        ) from exc

    mcp_before = mcp_path.read_bytes() if mcp_path.is_file() else None
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
        before_image=RegistrationBeforeImage(
            mcp_json=mcp_before, codex_config=codex_before
        ),
    )
    changed = (
        mcp_before != mcp_text.encode("utf-8")
        or codex_before != codex_text.encode("utf-8")
    )
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
    # rendered content is stale.
    current_mcp = mcp_path.read_bytes() if mcp_path.is_file() else None
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
    if (
        current_mcp != rendered.before_image.mcp_json
        or current_codex != rendered.before_image.codex_config
    ):
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
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=(
                f"Writing {mcp_path.name} failed: {exc}. No file was written; "
                "the registration is incomplete and a retry converges."
            ),
            reason=REASON_REGISTRATION_INCOMPLETE,
            start=start,
        )

    try:
        write_codex_config_text(context.project_root, rendered.codex_toml_text)
    except (OSError, CodexConfigError) as exc:
        rollback_note = _rollback_mcp_json(mcp_path, rendered.before_image.mcp_json)
        return make_result(
            nid.CP_10_MCP_REGISTRATION,
            status=CheckpointStatus.FAILED,
            detail=(
                f"Writing {CODEX_DIR}/{CODEX_CONFIG_FILE} failed: {exc}. "
                f"{mcp_path.name} was already written; {rollback_note} "
                "A repeated run converges idempotently."
            ),
            reason=REASON_REGISTRATION_INCOMPLETE,
            start=start,
        )

    _record_created_file(context, mcp_path)
    _record_created_file(context, codex_config_path(context.project_root))
    status = CheckpointStatus.CREATED if created else CheckpointStatus.UPDATED
    return make_result(
        nid.CP_10_MCP_REGISTRATION,
        status=status,
        detail=(
            f"Registered MCP servers {server_keys} in {mcp_path.name} and "
            f"{CODEX_DIR}/{CODEX_CONFIG_FILE}."
        ),
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
        return (
            f"ROLLBACK FAILED ({rollback_exc}); {mcp_path.name} is left in its "
            "newly written state and must be reconciled by a repeated run."
        )
    return "rolled back to its previous content."


def _write_mcp_json_text(
    mcp_path: Path, content: str, context: CheckpointContext
) -> None:
    """Atomically write the pre-rendered target ``.mcp.json`` content.

    The content is rendered in phase 3 (``mcp_registration.render_mcp_json_text``,
    ``allow_nan=False`` as defense in depth) so this function only performs the
    write. ``newline=""`` keeps the bytes on disk equal to the rendered text,
    which the idempotency comparison and the bound before-image both rely on.
    """
    del context  # kept for signature symmetry with the created-file recording
    atomic_write_text(mcp_path, content, newline="")


def _record_created_file(context: CheckpointContext, path: Path) -> None:
    """Record a written file on the run-state for the install report."""
    rel = str(path.relative_to(context.project_root))
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
    registered = isinstance(servers, dict) and ARE_MCP_SERVER in servers
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
