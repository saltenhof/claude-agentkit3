"""Installer-side MCP registration: one spec, one probe, two projections.

Owns the installer half of AG3-175 Scope 1 (FK-50 §50.3 CP 10 is the contract
owner for *whether/when* a registration happens):

* the rendered command / args / env of the story-knowledge-base server,
* the bridge from the FK-13 :class:`McpServerSpec` into the harness-neutral
  :class:`DesiredMcpServer` (value-equal, asserted),
* the LOSSLESS bridge into the conformance probe's :class:`McpServerCommand`,
* the ``.mcp.json`` projection (semantic UPSERT merge, foreign entries kept),
* the probe receipt (:class:`ProbedRegistration`) whose digest binds the probed
  registration to the written one.

Why the bridge does not go through ``server_command_from_mcp_entry``: that
function (``mcp_conformance/check.py:202-227``) builds an ``McpServerCommand``
from a ``.mcp.json`` entry and returns it WITHOUT ``cwd`` — it cannot carry the
containment boundary at all. CP 10 previously compensated by rebuilding the
command with a different ``cwd``, so the probed and the written specs provably
diverged. Here the projection goes spec -> command directly, all four fields.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.boundary.filesystem import matches_resolved_path_owner
from agentkit.backend.core_types.mcp_server_registration import (
    AK3_SERVER_SHAPES,
    MCP_JSON_STDIO_TYPE,
    REGISTERED_ENV_KEYS,
    STORY_KNOWLEDGE_BASE_SERVER,
    DesiredMcpServer,
    McpServerRegistrationError,
    before_image_fingerprint,
    registration_digest,
)
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_MCP_PROTOCOL_ERROR,
)
from agentkit.backend.installer.mcp_conformance import (
    DEFAULT_TIMEOUT_SECONDS,
    McpServerCommand,
    check_mcp_conformance,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from agentkit.backend.vectordb.runtime_binding import McpServerSpec

#: The module the registered interpreter must be able to import for the
#: story-knowledge-base MCP server to start at all.
_MCP_ENTRYPOINT_MODULE: str = "agentkit.backend.vectordb.engine"

#: Seconds granted to the one-shot import preflight below.
_INTERPRETER_PROBE_TIMEOUT_SECONDS: float = 60.0


def resolve_story_knowledge_base_command() -> str:
    """Return the ABSOLUTE interpreter path registered for the MCP server.

    The installer interpreter owner proves the dedicated environment and returns
    its absolute interpreter path. Registering it removes the harness process'
    ``PATH`` from the decision entirely.

    A bare ``"python"`` was registered until 2026-08-02. It let whatever
    interpreter happened to be first on the harness' ``PATH`` start the server —
    an interpreter that generally does NOT carry AK3's dependencies, because AK3
    lives in its own venv. The failure surfaced only at first use, as a missing
    third-party import, long after the installer had reported success.

    Raises:
        McpServerRegistrationError: If the running interpreter cannot be
            resolved to a real file (fail-closed; never register a guess).
    """
    from agentkit.backend.installer.interpreter import (
        InterpreterResolutionError,
        resolve_ak3_interpreter,
    )

    try:
        return str(resolve_ak3_interpreter())
    except InterpreterResolutionError as exc:
        raise McpServerRegistrationError(str(exc)) from exc


def verify_interpreter_serves_ak3(
    command: str,
    *,
    runner: object | None = None,
) -> None:
    """Fail closed unless ``command`` can import the MCP server entrypoint.

    Registering an interpreter that cannot import
    ``agentkit.backend.vectordb.engine`` produces a registration that looks
    successful and dies on first use. This runs the import ONCE, at registration
    time, and turns the failure into an install failure instead.

    Args:
        command: The interpreter path about to be registered.
        runner: Injection seam for the subprocess call (tests); defaults to
            :func:`subprocess.run`.

    Raises:
        McpServerRegistrationError: If the interpreter is missing, times out, or
            cannot import the entrypoint module (with the import error attached).
    """
    run = subprocess.run if runner is None else runner
    argv = [command, "-c", f"import {_MCP_ENTRYPOINT_MODULE}"]
    try:
        completed = run(  # type: ignore[operator]
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_INTERPRETER_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise McpServerRegistrationError(
            f"registered MCP interpreter {command!r} could not be executed "
            f"({exc}); the MCP server would fail on first use (fail-closed)."
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise McpServerRegistrationError(
            f"registered MCP interpreter {command!r} cannot import "
            f"{_MCP_ENTRYPOINT_MODULE!r} (exit {completed.returncode}): {detail}. "
            "The MCP server would start and immediately die; install AK3 and its "
            "dependencies into THIS interpreter (fail-closed)."
        )

#: Argument vector of the story-knowledge-base MCP server.
#:
#: ``agentkit.backend.vectordb.engine`` — NOT ``...vectordb.mcp_server``.
#: ``mcp_server`` is a LIBRARY module: running it as ``-m`` executes the module
#: body and exits 0 without serving anything, which the AG3-164 conformance gate
#: correctly reports as ``mcp_process_exited``. The executable stdio entry point
#: is ``engine.main`` (``engine.py:1258``, wired at ``engine.py:1311-1312`` and
#: exported in ``engine.__all__``); it reads the env, composes the production
#: engine and serves over stdio, failing closed with exit 1 otherwise.
STORY_KNOWLEDGE_BASE_ARGS: tuple[str, ...] = AK3_SERVER_SHAPES[STORY_KNOWLEDGE_BASE_SERVER].args

#: Artifact key of the Claude-Code project configuration in a before-image.
MCP_JSON_ARTIFACT: str = "mcp_json"

#: Artifact key of the Codex project configuration in a before-image.
CODEX_CONFIG_ARTIFACT: str = "codex_config"


def build_registration_env(
    *,
    project_id: str,
    weaviate_http_endpoint: str,
    weaviate_grpc_endpoint: str,
    concepts_dir: str,
    stories_dir: str,
) -> dict[str, str]:
    """Build the fully rendered registration environment (five keys, D2).

    Emitted in :data:`REGISTERED_ENV_KEYS` order so the rendering is
    deterministic. No value is defaulted or synthesised: every one is an explicit
    configuration value, which is what D2 demands.

    Args:
        project_id: Authoritative project id (``resolve_authoritative_project_id``).
        weaviate_http_endpoint: Configured HTTP endpoint (no default).
        weaviate_grpc_endpoint: Configured gRPC endpoint (no default).
        concepts_dir: Absolute concept corpus root.
        stories_dir: Absolute story corpus root.

    Returns:
        The environment mapping for the registered server.

    Raises:
        McpServerRegistrationError: If any value is empty after stripping.
    """
    values = {
        "PROJECT_ID": project_id,
        "WEAVIATE_HTTP_ENDPOINT": weaviate_http_endpoint,
        "WEAVIATE_GRPC_ENDPOINT": weaviate_grpc_endpoint,
        "AGENTKIT_CONCEPTS_DIR": concepts_dir,
        "AGENTKIT_STORIES_DIR": stories_dir,
    }
    for key in REGISTERED_ENV_KEYS:
        value = values[key]
        if not isinstance(value, str) or not value.strip():
            raise McpServerRegistrationError(
                f"registration env key {key!r} is missing/empty; it is an explicit "
                "configuration value with no default (fail-closed, D2)."
            )
    return {key: values[key] for key in REGISTERED_ENV_KEYS}


def desired_server_from_spec(
    name: str,
    spec: McpServerSpec,
    *,
    required: bool = True,
) -> DesiredMcpServer:
    """Project an FK-13 ``McpServerSpec`` into a :class:`DesiredMcpServer`.

    The FK-13 spec is the SSOT for the started process ("consumed UNCHANGED by
    AG3-175", ``runtime_binding.py`` module docstring) and this is the ONLY place
    the projection happens. It asserts value equality between the spec's own
    attributes and its ``env``, so the projection can never carry different
    values than the spec claims (AC 5, "wertgleich").

    Args:
        name: Server key in the harness configuration.
        spec: The validated FK-13 spec to project.
        required: Whether the harness must treat the server as mandatory.

    Returns:
        The immutable desired registration.

    Raises:
        McpServerRegistrationError: If the spec's ``env`` diverges from its own
            attributes, or does not carry exactly :data:`REGISTERED_ENV_KEYS`.
    """
    env = spec.env_dict()
    expected = {
        "PROJECT_ID": spec.project_id,
        "WEAVIATE_HTTP_ENDPOINT": spec.weaviate_http_endpoint,
        "WEAVIATE_GRPC_ENDPOINT": spec.weaviate_grpc_endpoint,
    }
    for key, attribute_value in expected.items():
        if env.get(key) != attribute_value:
            raise McpServerRegistrationError(
                f"server {name!r}: spec attribute for {key!r} is "
                f"{attribute_value!r} but its env carries {env.get(key)!r}; the "
                "projection must be value-equal to the spec (AC 5, fail-closed)."
            )
    if set(env) != set(REGISTERED_ENV_KEYS):
        missing = sorted(set(REGISTERED_ENV_KEYS) - set(env))
        unexpected = sorted(set(env) - set(REGISTERED_ENV_KEYS))
        raise McpServerRegistrationError(
            f"server {name!r}: env must carry exactly the registered keys; "
            f"missing={missing}, unexpected={unexpected}. The started process "
            "needs every one of them (fail-closed)."
        )
    return DesiredMcpServer(
        name=name,
        command=spec.command,
        args=tuple(spec.args),
        cwd=spec.cwd,
        env=tuple((key, env[key]) for key in REGISTERED_ENV_KEYS),
        required=required,
    )


def server_command_from_desired(server: DesiredMcpServer) -> McpServerCommand:
    """Bridge a desired registration into the conformance probe's command.

    Lossless by construction: ``command``, ``args``, ``env`` AND ``cwd`` all
    travel. This is the fix for the divergence described in the module
    docstring — the probed command is built from exactly the object that gets
    written, so probed and written specs cannot differ in ``cwd`` (or anything
    else).

    Args:
        server: The desired registration.

    Returns:
        The probe command for :func:`check_mcp_conformance`.
    """
    return McpServerCommand(
        command=server.command,
        args=server.args,
        env=server.env_dict(),
        cwd=server.cwd,
    )


@dataclass(frozen=True, slots=True)
class RegistrationBeforeImage:
    """Byte-exact state of both configuration files before the first write.

    ``None`` means the file did not exist — a genuine state distinct from empty
    content, because a rollback must DELETE in that case rather than leave an
    empty file behind (D6).

    Attributes:
        mcp_json: Bytes of the target ``.mcp.json``, or ``None`` if absent.
        codex_config: Bytes of the target ``.codex/config.toml``, or ``None``.
    """

    mcp_json: bytes | None
    codex_config: bytes | None

    def fingerprints(self) -> dict[str, str | None]:
        """Return the digest representation bound into the registration digest."""
        return {
            MCP_JSON_ARTIFACT: before_image_fingerprint(self.mcp_json),
            CODEX_CONFIG_ARTIFACT: before_image_fingerprint(self.codex_config),
        }


@dataclass(frozen=True, slots=True)
class RenderedRegistration:
    """Both harness projections, fully rendered, bound to their before-image.

    Constructed in the read/conflict-check/render phase, BEFORE the conformance
    probe and before any write (D6: a parse or conflict error must produce zero
    writes).

    Attributes:
        servers: The desired servers, sorted by name.
        mcp_json_text: Fully rendered ``.mcp.json`` content.
        codex_toml_text: Fully rendered ``.codex/config.toml`` content.
        before_image: Byte-exact prior state of both files.
    """

    servers: tuple[DesiredMcpServer, ...]
    mcp_json_text: str
    codex_toml_text: str
    before_image: RegistrationBeforeImage

    def digest(self) -> str:
        """Return the digest over specs, both rendered texts and the before-image."""
        return registration_digest(
            self.servers,
            mcp_json_text=self.mcp_json_text,
            codex_toml_text=self.codex_toml_text,
            before_image=self.before_image.fingerprints(),
        )


@dataclass(frozen=True, slots=True)
class ProbedRegistration:
    """Receipt proving a rendered registration passed the conformance probe.

    The only object the write phase accepts. There is no code path from a raw
    ``McpServerSpec`` or :class:`DesiredMcpServer` to a write.

    Honest limitation: Python offers no capability boundary. A caller that
    recomputes :attr:`digest_at_probe` for a substituted registration is no
    longer changing a field after the probe — it is forging a receipt, and the
    correct response to that is to probe again. What :meth:`verify_binding`
    guarantees is that in-place mutation is impossible and every substitution is
    detected.

    Attributes:
        rendered: The rendered registration that was probed.
        digest_at_probe: :meth:`RenderedRegistration.digest` captured at probe
            time.
        tool_names: Per server, the tool names the probe observed (evidence).
    """

    rendered: RenderedRegistration
    digest_at_probe: str
    tool_names: tuple[tuple[str, tuple[str, ...]], ...]

    def verify_binding(self) -> None:
        """Re-verify that nothing changed between the probe and the write.

        Raises:
            McpServerRegistrationError: If the registration digest no longer
                matches the digest captured at probe time.
        """
        current = self.rendered.digest()
        if current != self.digest_at_probe:
            raise McpServerRegistrationError(
                "the MCP registration changed after the conformance probe "
                f"(digest at probe {self.digest_at_probe}, now {current}); "
                "refusing to write an unprobed registration (AC 5, fail-closed)."
            )


def probe_registration(
    rendered: RenderedRegistration,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[ProbedRegistration | None, tuple[str, str] | None]:
    """Probe every desired server, immediately before the first write.

    Runs the generic AG3-164 conformance check (process start, ``initialize``,
    non-empty ``tools/list``) on the command bridged from each desired server.
    Servers are probed in name order so a failure is reported deterministically.

    Args:
        rendered: The fully rendered registration to probe.
        timeout_seconds: Per-server probe budget.

    Returns:
        ``(receipt, None)`` when every server passed, else ``(None, (reason,
        detail))`` with a machine-readable CP 10 reason. Never writes anything.
    """
    observed: list[tuple[str, tuple[str, ...]]] = []
    for server in sorted(rendered.servers, key=lambda item: item.name):
        command = server_command_from_desired(server)
        try:
            result = check_mcp_conformance(command, timeout_seconds=timeout_seconds)
        except Exception as exc:  # noqa: BLE001 — CP 10 boundary: named FAILED
            return None, (
                REASON_MCP_PROTOCOL_ERROR,
                f"MCP conformance internal fault for server {server.name!r}: {exc}. Registration was not written.",
            )
        if not result.ok:
            reason = result.reason.value if result.reason is not None else REASON_MCP_PROTOCOL_ERROR
            return None, (
                reason,
                f"MCP conformance failed for server {server.name!r}: {result.detail} Registration was not written.",
            )
        observed.append((server.name, tuple(result.tool_names)))
    return (
        ProbedRegistration(
            rendered=rendered,
            digest_at_probe=rendered.digest(),
            tool_names=tuple(observed),
        ),
        None,
    )


def merge_mcp_json_servers(
    existing_root: Mapping[str, object],
    servers: Sequence[DesiredMcpServer],
) -> tuple[dict[str, object], bool]:
    """Merge desired servers into a strictly loaded ``.mcp.json`` root (UPSERT).

    Foreign ``mcpServers`` entries are preserved; nothing is ever removed. The
    caller must pass a root produced by the strict loader, so a present
    ``mcpServers`` is guaranteed to be an object — a non-object is a programming
    error here, not a silent shape replacement.

    Args:
        existing_root: Strictly loaded root mapping (``{}`` when the file is absent).
        servers: The desired servers to upsert.

    Returns:
        ``(merged_root, changed)``.

    Raises:
        TypeError: If ``mcpServers`` is present but not an object.
    """
    root: dict[str, object] = dict(existing_root)
    raw = root.get("mcpServers")
    if raw is None:
        merged: dict[str, object] = {}
    elif isinstance(raw, dict):
        merged = dict(raw)
    else:
        msg = f"mcpServers must be a JSON object after strict load; got {type(raw).__name__}"
        raise TypeError(msg)
    changed = False
    for server in servers:
        _reject_foreign_occupation(merged, server)
        entry = server.to_mcp_json_entry()
        current = merged.get(server.name)
        if isinstance(current, dict):
            # Identity already matched (else the rejection above fired), so this IS
            # AK3's own entry: upsert the owned fields and PRESERVE any unknown
            # harness-specific field, exactly as the Codex writer does for its own
            # table. Dropping them here was the positive-direction half of the same
            # asymmetry: one format preserved foreign data, the other discarded it.
            entry = {**current, **entry}
        if current != entry:
            merged[server.name] = entry
            changed = True
    root["mcpServers"] = merged
    return root, changed


def _reject_foreign_occupation(existing: Mapping[str, object], server: DesiredMcpServer) -> None:
    """Reject an AK3 server name occupied by a DIFFERENT program (``.mcp.json``).

    The Codex writer has always refused to overwrite a foreign registration under
    an AK3 server name; ``.mcp.json`` silently clobbered it. That asymmetry was a
    real gap against PO decision D6: the same registration would be rejected in one
    file and overwritten in the other, so "is this entry ours?" had two different
    answers depending on the format.

    The identity rule is deliberately the SAME one the Codex predicate uses --
    ``command`` plus ``args``, mirroring FK-76 §76.5.1's handler identity. An entry
    that exists but carries no command/args at all is an ambiguous occupation and
    is rejected too, never treated as a free slot.

    Args:
        existing: The current ``mcpServers`` mapping.
        server: The desired registration.

    Raises:
        McpServerRegistrationError: If the name is occupied by a different or
            ambiguous registration. No mutation happens.
    """
    current = existing.get(server.name)
    if not isinstance(current, dict):
        return
    current_command = current.get("command")
    current_args = current.get("args")
    if current_command == server.command and list(current_args or []) == list(server.args):
        return
    raise McpServerRegistrationError(
        f"target .mcp.json server {server.name!r} is occupied by a different or "
        f"ambiguous registration (command={current_command!r}, "
        f"args={current_args!r}); AK3 would register command={server.command!r}, "
        f"args={list(server.args)!r}. Refusing to overwrite a foreign registration "
        "under an AK3 server name (fail-closed, same identity rule as the Codex "
        "writer)."
    )


def assert_cwd_is_project_root(servers: Sequence[DesiredMcpServer], project_root: Path) -> None:
    """Assert every desired ``cwd`` IS the project root, before the probe.

    ``cwd`` is the containment boundary of the registered process and never a
    configuration source (PO decision D2). Production derives it from
    ``context.project_root``, so today it cannot be wrong -- this is the
    fail-closed negative invariant AC 5 asks for, held at the boundary rather than
    trusted: a future refactor that starts deriving ``cwd`` from somewhere else
    (an env var, a config value, the process cwd) fails here instead of silently
    probing one directory and registering another.

    Args:
        servers: The desired registrations.
        project_root: The authoritative project root.

    Raises:
        McpServerRegistrationError: On any deviation, before anything is probed
            or written.
    """
    expected = project_root.resolve()
    for server in servers:
        try:
            actual = Path(server.cwd).resolve()
        except OSError as exc:  # pragma: no cover - unresolvable path
            raise McpServerRegistrationError(
                f"server {server.name!r}: cwd {server.cwd!r} cannot be resolved: {exc} (fail-closed)."
            ) from exc
        if actual != expected:
            raise McpServerRegistrationError(
                f"server {server.name!r}: cwd {server.cwd!r} resolves to {actual}, "
                f"not to the project root {expected}. The containment boundary is "
                "always the project root and never a second configuration source "
                "(D2, fail-closed)."
            )


def render_mcp_json_text(
    existing_root: Mapping[str, object],
    servers: Sequence[DesiredMcpServer],
) -> tuple[str, bool]:
    """Render the full ``.mcp.json`` content for the merged registration.

    The serialisation is byte-identical in form to what CP 10 wrote before
    (``indent=2``, ``sort_keys=True``, ``allow_nan=False``, trailing newline), so
    the change is confined to the entry CONTENT — existing snapshot expectations
    about the file's shape keep holding.

    Args:
        existing_root: Strictly loaded root mapping.
        servers: The desired servers to upsert.

    Returns:
        ``(text, changed)``.
    """
    merged, changed = merge_mcp_json_servers(existing_root, servers)
    text = json.dumps(merged, indent=2, sort_keys=True, allow_nan=False) + "\n"
    return text, changed


def render_mcp_json_without_ak3(
    raw: bytes,
    *,
    project_root: Path,
    resolved_command_owners: Mapping[str, str] | None = None,
) -> str:
    """Surgically remove recognised AK3 fields and preserve foreign JSON."""
    loaded = _strict_detach_root(raw)
    servers = loaded.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        raise McpServerRegistrationError(".mcp.json mcpServers must be an object")
    if isinstance(servers, dict):
        removed = _remove_owned_mcp_servers(
            servers,
            project_root=project_root,
            resolved_command_owners=resolved_command_owners,
        )
        if removed and not servers:
            del loaded["mcpServers"]
        if not removed:
            return raw.decode("utf-8")
    return json.dumps(loaded, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _strict_detach_root(raw: bytes) -> dict[str, object]:
    from agentkit.backend.installer.strict_json import (
        contains_lone_surrogate,
        contains_non_finite_float,
        exceeds_max_json_nesting,
        reject_duplicate_object_pairs,
        reject_non_json_constant,
    )

    try:
        text = raw.decode("utf-8")
        loaded = json.loads(
            text,
            parse_constant=reject_non_json_constant,
            object_pairs_hook=reject_duplicate_object_pairs,
        )
    except (RecursionError, ValueError) as exc:
        raise McpServerRegistrationError(f"Cannot surgically detach .mcp.json: {exc}") from exc
    if not isinstance(loaded, dict):
        raise McpServerRegistrationError(".mcp.json root must be an object")
    if exceeds_max_json_nesting(loaded):
        raise McpServerRegistrationError(".mcp.json exceeds the maximum nesting depth")
    if contains_non_finite_float(loaded):
        raise McpServerRegistrationError(".mcp.json contains a non-finite number")
    if contains_lone_surrogate(loaded):
        raise McpServerRegistrationError(".mcp.json contains a lone Unicode surrogate")
    return loaded


def _remove_owned_mcp_servers(
    servers: dict[str, object],
    *,
    project_root: Path,
    resolved_command_owners: Mapping[str, str] | None,
) -> bool:
    removed = False
    for name, shape in AK3_SERVER_SHAPES.items():
        entry = servers.get(name)
        if not isinstance(entry, dict):
            continue
        owned_fields = {"type", "command", "args", "cwd", "env"}
        owned_entry = {
            field: value for field, value in entry.items() if field in owned_fields
        }
        if set(owned_entry) != owned_fields:
            continue
        if owned_entry["type"] != MCP_JSON_STDIO_TYPE:
            continue
        args = entry.get("args")
        resolved_owner = (
            None
            if resolved_command_owners is None
            else resolved_command_owners.get(name)
        )
        if not shape.matches_command(
            entry.get("command"),
            resolved_owner_command=resolved_owner,
            path_owner_matcher=matches_resolved_path_owner,
        ) or not isinstance(args, list):
            continue
        if tuple(args) != shape.args:
            continue
        cwd = owned_entry["cwd"]
        if not isinstance(cwd, str) or not cwd.strip():
            continue
        if not matches_resolved_path_owner(cwd, str(project_root.absolute())):
            continue
        env = owned_entry["env"]
        if not isinstance(env, dict) or set(env) != set(shape.env_keys):
            continue
        if not all(isinstance(value, str) and value.strip() for value in env.values()):
            continue
        for field in owned_fields:
            if field in entry:
                del entry[field]
                removed = True
        if not entry:
            del servers[name]
    return removed


__all__ = [
    "CODEX_CONFIG_ARTIFACT",
    "MCP_JSON_ARTIFACT",
    "STORY_KNOWLEDGE_BASE_ARGS",
    "STORY_KNOWLEDGE_BASE_SERVER",
    "ProbedRegistration",
    "RegistrationBeforeImage",
    "RenderedRegistration",
    "assert_cwd_is_project_root",
    "build_registration_env",
    "desired_server_from_spec",
    "merge_mcp_json_servers",
    "probe_registration",
    "render_mcp_json_text",
    "render_mcp_json_without_ak3",
    "server_command_from_desired",
]
