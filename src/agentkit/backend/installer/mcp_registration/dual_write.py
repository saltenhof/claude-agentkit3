"""Two-file dual-harness MCP registration (AG3-175 AC 6 / Review 175-P1-1).

Honest semantics — **no** cross-file atomic filesystem transaction:

1. Both existing files are read, conflict-checked, and fully rendered
   **before** the first write.
2. Conformance / parse / conflict / probe-binding errors → **null writes**
   (both files byte-identical to the pre-write state).
3. Each single-file write is atomic.
4. I/O error **after** the first write → best-effort rollback from the bound
   before-image + named ``registration_incomplete``.
5. A retry run converges idempotently.

The crash window between the two files is documented, not sold as atomicity.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_MCP_CONFIGURATION_INVALID,
    REASON_REGISTRATION_INCOMPLETE,
)
from agentkit.backend.installer.file_ops import atomic_write_text
from agentkit.backend.installer.mcp_registration.bound_spec import (
    BoundMcpServerRegistration,
    ProbeBindingError,
    project_spec_to_claude_entry,
    project_spec_to_codex_entry,
    require_probe_binding,
)
from agentkit.backend.vectordb.project_binding import ProjectBindingError, bind_project
from agentkit.backend.vectordb.runtime_binding import (
    ENV_WEAVIATE_GRPC_PORT,
    ENV_WEAVIATE_HOST,
    ENV_WEAVIATE_HTTP_PORT,
    McpServerSpec,
    RuntimeBindingError,
    build_mcp_server_spec,
)
from agentkit.harness_client.harness_adapters.codex_mcp_config_writer import (
    CodexMcpConfigError,
    load_codex_mcp_document,
    project_codex_mcp_config_path,
    render_merged_codex_mcp,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.installer.checkpoint_engine.context import CheckpointContext

#: Default story-kb command (AG3-174 console script).
_STORY_KB_COMMAND: Final = "agentkit-mcp-story-kb"
#: Env aliases accepted when resolving the Weaviate endpoint for registration.
_ENV_HOST_ALIASES: Final = (ENV_WEAVIATE_HOST, "AK3_WEAVIATE_HOST")
_ENV_HTTP_ALIASES: Final = (ENV_WEAVIATE_HTTP_PORT, "AK3_WEAVIATE_HTTP_PORT")
_ENV_GRPC_ALIASES: Final = (ENV_WEAVIATE_GRPC_PORT, "AK3_WEAVIATE_GRPC_PORT")


class DualRegistrationError(Exception):
    """Named dual-registration failure with stable reason token."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class DualRegistrationPlan:
    """Fully prepared dual registration ready for write (or dry-run report).

    Attributes:
        bound: Probe-bound story-kb registration (required when dual write).
        mcp_json_path: Target-project ``.mcp.json``.
        codex_path: Target-project ``.codex/config.toml``.
        mcp_json_before: Raw before-image bytes (``None`` if file absent).
        codex_before: Raw before-image bytes (``None`` if file absent).
        mcp_json_rendered: Full rendered ``.mcp.json`` text to write.
        codex_rendered: Full rendered Codex TOML text to write.
        mcp_json_changed: Whether ``.mcp.json`` would change.
        codex_changed: Whether ``.codex/config.toml`` would change.
        mcp_json_root: Merged root dict (for callers that need inspection).
    """

    bound: BoundMcpServerRegistration
    mcp_json_path: Path
    codex_path: Path
    mcp_json_before: bytes | None
    codex_before: bytes | None
    mcp_json_rendered: str
    codex_rendered: str
    mcp_json_changed: bool
    codex_changed: bool
    mcp_json_root: dict[str, object] = field(repr=False)


@dataclass(frozen=True, slots=True)
class DualWriteResult:
    """Outcome of applying a prepared dual-registration plan."""

    mcp_json_written: bool
    codex_written: bool
    created_mcp_json: bool
    created_codex: bool


def build_story_kb_spec(context: CheckpointContext) -> McpServerSpec:
    """Render the story-knowledge-base :class:`McpServerSpec` once for CP 10.

    Endpoint and ``PROJECT_ID`` come exclusively into ``env``. ``cwd`` is the
    project root containment boundary. No localhost default is invented when
    endpoint values are missing (fail-closed).
    """
    host, http_port, grpc_port = _resolve_weaviate_endpoint(context)
    project_id = (context.config.project_key or "").strip()
    if not project_id:
        raise DualRegistrationError(
            REASON_MCP_CONFIGURATION_INVALID,
            "project_key is empty; cannot bind PROJECT_ID for MCP registration "
            "(fail-closed).",
        )
    root = context.project_root
    # AG3-176 R5: no silent root/concepts or root/stories invent. Prefer the
    # entry-validated ProjectConfig when present; otherwise bind_project must
    # succeed fail-closed (no directory inventing).
    try:
        if context.run_state.project_config is not None:
            project = bind_project(
                root,
                project_id=project_id,
                config=context.run_state.project_config,
            )
        else:
            project = bind_project(root, project_id=project_id)
        return build_mcp_server_spec(
            project=project,
            weaviate_host=host,
            weaviate_http_port=http_port,
            weaviate_grpc_port=grpc_port,
            command=_STORY_KB_COMMAND,
            args=(),
        )
    except (ProjectBindingError, RuntimeBindingError) as exc:
        raise DualRegistrationError(
            REASON_MCP_CONFIGURATION_INVALID,
            f"project binding failed for MCP registration (fail-closed, "
            f"no directory inventing, AG3-176 R5): {exc}",
        ) from exc


def prepare_dual_registration(
    *,
    project_root: Path,
    bound: BoundMcpServerRegistration,
    existing_mcp_json_root: dict[str, object],
    mcp_json_before: bytes | None,
    other_mcp_json_servers: dict[str, object],
    mcp_json_renderer: Callable[[dict[str, object]], str],
) -> DualRegistrationPlan:
    """Validate probe binding, merge both documents, render fully (no writes).

    Args:
        project_root: Target project root.
        bound: Probe-bound story-kb registration.
        existing_mcp_json_root: Already strict-loaded ``.mcp.json`` root.
        mcp_json_before: Raw before-image of ``.mcp.json`` (or ``None``).
        other_mcp_json_servers: Additional desired ``mcpServers`` entries
            (e.g. ARE) merged alongside the bound Spec projection.
        mcp_json_renderer: ``(root: dict) -> str`` JSON serializer used by CP10.

    Raises:
        DualRegistrationError: On probe-binding mismatch or Codex parse/merge
            failure. No file is written.
    """
    try:
        require_probe_binding(bound)
    except ProbeBindingError as exc:
        raise DualRegistrationError(exc.reason, exc.detail) from exc

    claude_entry = project_spec_to_claude_entry(bound.spec)
    desired_servers: dict[str, object] = {bound.server_id: claude_entry}
    desired_servers.update(other_mcp_json_servers)

    merged_mcp, mcp_changed = _merge_mcp_json_servers(
        existing_mcp_json_root, desired_servers
    )
    mcp_path = project_root / ".mcp.json"
    mcp_rendered = mcp_json_renderer(merged_mcp)

    _codex_root, codex_before, codex_err = load_codex_mcp_document(project_root)
    if codex_err is not None:
        raise DualRegistrationError(
            REASON_MCP_CONFIGURATION_INVALID,
            f"Target .codex/config.toml is invalid; refusing registration "
            f"without mutation: {codex_err}.",
        )
    # Surgical merge needs the raw source text (empty when file absent) so
    # foreign TOML constructs are never re-serialized (Review 175-R01/R02).
    existing_codex_text = (
        "" if codex_before is None else codex_before.decode("utf-8")
    )

    try:
        codex_entry = project_spec_to_codex_entry(bound.spec)
        codex_rendered, codex_changed = render_merged_codex_mcp(
            existing_codex_text, bound.server_id, codex_entry
        )
    except (CodexMcpConfigError, UnicodeDecodeError) as exc:
        if isinstance(exc, UnicodeDecodeError):
            raise DualRegistrationError(
                REASON_MCP_CONFIGURATION_INVALID,
                f"Target .codex/config.toml is not valid UTF-8: {exc}.",
            ) from exc
        raise DualRegistrationError(exc.reason, exc.detail) from exc

    # Re-check probe binding immediately before returning a writeable plan.
    try:
        require_probe_binding(bound)
    except ProbeBindingError as exc:
        raise DualRegistrationError(exc.reason, exc.detail) from exc

    return DualRegistrationPlan(
        bound=bound,
        mcp_json_path=mcp_path,
        codex_path=project_codex_mcp_config_path(project_root),
        mcp_json_before=mcp_json_before,
        codex_before=codex_before,
        mcp_json_rendered=mcp_rendered,
        codex_rendered=codex_rendered,
        mcp_json_changed=mcp_changed or not mcp_path.is_file(),
        codex_changed=codex_changed or not project_codex_mcp_config_path(project_root).is_file(),
        mcp_json_root=merged_mcp,
    )


def apply_dual_registration_writes(plan: DualRegistrationPlan) -> DualWriteResult:
    """Apply the prepared dual-file writes with honest partial-failure semantics.

    Raises:
        DualRegistrationError: ``registration_incomplete`` after a mid-write
            I/O failure (best-effort rollback attempted), or probe-binding
            mismatch if the Spec drifted between prepare and apply.
    """
    try:
        require_probe_binding(plan.bound)
    except ProbeBindingError as exc:
        raise DualRegistrationError(exc.reason, exc.detail) from exc

    if not plan.mcp_json_changed and not plan.codex_changed:
        return DualWriteResult(
            mcp_json_written=False,
            codex_written=False,
            created_mcp_json=False,
            created_codex=False,
        )

    created_mcp = not plan.mcp_json_path.is_file()
    created_codex = not plan.codex_path.is_file()
    mcp_written = False
    codex_written = False

    # Write order: .mcp.json first, then Codex. Crash window is documented.
    try:
        if plan.mcp_json_changed:
            atomic_write_text(plan.mcp_json_path, plan.mcp_json_rendered, newline="\n")
            mcp_written = True
        if plan.codex_changed:
            atomic_write_text(plan.codex_path, plan.codex_rendered, newline="\n")
            codex_written = True
    except OSError as exc:
        _best_effort_rollback(plan, mcp_written=mcp_written, codex_written=codex_written)
        raise DualRegistrationError(
            REASON_REGISTRATION_INCOMPLETE,
            "Dual-harness MCP registration incomplete after I/O error on the "
            f"second phase: {exc}. Best-effort rollback from the bound "
            "before-image was attempted. Retry converges idempotently "
            f"(reason={REASON_REGISTRATION_INCOMPLETE}).",
        ) from exc

    return DualWriteResult(
        mcp_json_written=mcp_written,
        codex_written=codex_written,
        created_mcp_json=created_mcp and mcp_written,
        created_codex=created_codex and codex_written,
    )


def _best_effort_rollback(
    plan: DualRegistrationPlan,
    *,
    mcp_written: bool,
    codex_written: bool,
) -> None:
    """Restore before-images when possible; never raise from rollback itself."""
    if mcp_written:
        _restore_before_image(plan.mcp_json_path, plan.mcp_json_before)
    if codex_written:
        _restore_before_image(plan.codex_path, plan.codex_before)


def _restore_before_image(path: Path, before: bytes | None) -> None:
    try:
        if before is None:
            if path.is_file() or path.is_symlink():
                path.unlink()
            return
        atomic_write_text(path, before.decode("utf-8"), newline="\n")
    except (OSError, UnicodeDecodeError):
        # Best-effort only — registration_incomplete remains the caller signal.
        try:
            if before is not None:
                path.write_bytes(before)
        except OSError:
            return


def _merge_mcp_json_servers(
    existing: dict[str, object],
    desired: dict[str, object],
) -> tuple[dict[str, object], bool]:
    root = dict(existing)
    servers_raw = root.get("mcpServers")
    if servers_raw is None:
        servers: dict[str, object] = {}
    elif isinstance(servers_raw, dict):
        servers = dict(servers_raw)
    else:
        raise DualRegistrationError(
            REASON_MCP_CONFIGURATION_INVALID,
            "mcpServers must be a JSON object after strict load; "
            f"got {type(servers_raw).__name__}",
        )
    changed = False
    for key, value in desired.items():
        if servers.get(key) != value:
            servers[key] = value
            changed = True
    root["mcpServers"] = servers
    return root, changed


def _resolve_weaviate_endpoint(context: CheckpointContext) -> tuple[str, int, int]:
    """Resolve Weaviate host/ports for Spec env — fail-closed, no silent default."""
    cfg = context.config
    host = _optional_str(getattr(cfg, "weaviate_host", None))
    http_port = _optional_int(getattr(cfg, "weaviate_http_port", None))
    grpc_port = _optional_int(getattr(cfg, "weaviate_grpc_port", None))

    yaml_data = context.run_state.project_yaml or {}
    vdb = yaml_data.get("vectordb")
    if not isinstance(vdb, dict):
        pipeline = yaml_data.get("pipeline")
        if isinstance(pipeline, dict):
            vdb = pipeline.get("vectordb")
    if isinstance(vdb, dict):
        if host is None:
            host = _optional_str(vdb.get("host"))
        if http_port is None:
            http_port = _optional_int(vdb.get("port") if "port" in vdb else vdb.get("http_port"))
        if grpc_port is None:
            grpc_port = _optional_int(vdb.get("grpc_port"))

    if host is None:
        host = _env_first(_ENV_HOST_ALIASES)
    if http_port is None:
        http_raw = _env_first(_ENV_HTTP_ALIASES)
        http_port = _optional_int(http_raw)
    if grpc_port is None:
        grpc_raw = _env_first(_ENV_GRPC_ALIASES)
        grpc_port = _optional_int(grpc_raw)

    missing: list[str] = []
    if not host:
        missing.append("WEAVIATE_HOST")
    if http_port is None or http_port <= 0:
        missing.append("WEAVIATE_HTTP_PORT")
    if grpc_port is None or grpc_port <= 0:
        missing.append("WEAVIATE_GRPC_PORT")
    if missing:
        raise DualRegistrationError(
            REASON_MCP_CONFIGURATION_INVALID,
            "Weaviate endpoint incomplete for MCP registration (fail-closed, "
            f"no localhost default): missing/invalid {missing}.",
        )
    assert host is not None and http_port is not None and grpc_port is not None
    return host, http_port, grpc_port


def _env_first(keys: tuple[str, ...]) -> str | None:
    for key in keys:
        raw = os.environ.get(key)
        if raw is not None and raw.strip():
            return raw.strip()
    return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


__all__ = [
    "DualRegistrationError",
    "DualRegistrationPlan",
    "DualWriteResult",
    "apply_dual_registration_writes",
    "build_story_kb_spec",
    "prepare_dual_registration",
]
