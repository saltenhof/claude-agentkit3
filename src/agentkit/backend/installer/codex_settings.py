"""Installer edge for the project-local Codex configuration.

The official AgentKit Codex hook entrypoint is the installed
``agentkit-hook-codex`` wrapper, resolved beside the central interpreter.
Target projects receive a project-local ``.codex/config.toml`` so Codex can
call that wrapper without a PATH lookup.

Split of responsibilities (AG3-175):

* The FORMAT — rendering, the semantic merge and the AK3-ownership predicate —
  belongs to FK-76 and lives in
  ``harness_client.harness_adapters.codex_config_toml``. There is exactly ONE
  writer; the former fixed-string whole-file builder and the bundle copy are gone.
* This module is the installer edge: it owns the target-project PATH, its
  containment proof, the atomic write and the idempotency decision. FK-76 §76.9
  fixes the direction (installer calls the harness adapter, never the reverse).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.boundary.filesystem import (
    FilesystemContainmentError,
    assert_project_local_file_path,
)
from agentkit.backend.exceptions import InstallationError
from agentkit.backend.installer.interpreter import render_ak3_wrapper_command
from agentkit.backend.installer.paths import CODEX_DIR, codex_config_path
from agentkit.backend.utils.io import atomic_write_text
from agentkit.harness_client.harness_adapters.codex_config_toml import (
    CodexConfigError,
    CodexConfigRejection,
    render_canonical_codex_config,
    render_codex_config,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.backend.core_types.mcp_server_registration import DesiredMcpServer

CODEX_HOOK_COMMAND = render_ak3_wrapper_command("agentkit-hook-codex")


def assert_project_local_codex_config(project_root: Path) -> Path:
    """Return ``.codex/config.toml`` after proving it cannot leave the project.

    AG3-175 AC 3 ("never a user path, not even via environment/symlink aliases").
    On Windows the realistic vector is a **junction**, not a symlink, so the
    directory check uses the tested primitive :func:`is_directory_link`
    (``path.is_symlink() or os.path.isjunction(path)``) — the same one the detach
    tree removals use.

    Args:
        project_root: The target-project root.

    Returns:
        The project-local configuration path.

    Raises:
        CodexConfigError: If ``.codex`` is a symlink/junction, the configuration
            file itself is a symlink, or the resolved directory escapes the
            project root. Nothing is read or written in that case.
    """
    try:
        return assert_project_local_file_path(
            project_root,
            Path(CODEX_DIR) / "config.toml",
        )
    except FilesystemContainmentError as exc:
        raise CodexConfigError(
            CodexConfigRejection.PATH_ESCAPES_PROJECT_ROOT,
            f"Codex configuration is not provably project-local: {exc} "
            "(containment violation, fail-closed).",
        ) from exc


def read_codex_config_bytes(project_root: Path) -> bytes | None:
    """Read the existing Codex configuration, or ``None`` when absent.

    Reads BYTES so invalid UTF-8 becomes a diagnosable rejection instead of a
    decoding crash, and so a before-image is byte-exact.

    Args:
        project_root: The target-project root.

    Returns:
        The file's bytes, or ``None`` if it does not exist.

    Raises:
        CodexConfigError: If the path is not project-local.
    """
    path = assert_project_local_codex_config(project_root)
    if not path.is_file():
        return None
    return path.read_bytes()


def build_codex_config_toml() -> str:
    """Return the AgentKit-managed Codex configuration with hooks only.

    Kept as the public name existing callers use. It renders from scratch, so it
    needs no ownership classification and therefore no project root — it is a thin
    call into the single writer rather than a competing fixed string.
    """
    return render_canonical_codex_config(
        hook_command=CODEX_HOOK_COMMAND, server_tables={}
    )


def render_project_codex_config(
    project_root: Path,
    servers: Sequence[DesiredMcpServer] = (),
    *,
    raw: bytes | None,
) -> str:
    """Render the full Codex configuration from ALREADY-CAPTURED bytes.

    Used by CP 10, which must render BOTH harness files before the first write
    (PO decision D6: a parse/conflict error yields zero writes).

    ``raw`` is a REQUIRED keyword and this function deliberately does NOT read the
    file: it used to, which meant CP 10 captured the before-image from one read and
    rendered from another. A concurrent foreign edit between the two could bind a
    NEWER before-image to a STALER rendering, and the pre-write guard would then
    find before-image and disk in agreement and authorise exactly the stale
    overwrite it exists to prevent — silently losing the foreign change. Making the
    bytes an explicit input is what removes the second read structurally rather
    than by discipline.

    Args:
        project_root: The target-project root (containment + ownership context).
        servers: The desired MCP server registrations.
        raw: The captured file bytes, or ``None`` when the file does not exist.

    Returns:
        The content a write would store.

    Raises:
        CodexConfigError: On any writer rejection (unreadable/invalid existing
            configuration, wrongly typed AK3-owned field, AK3 server name occupied
            by a different program).
    """
    return render_codex_config(
        raw,
        hook_command=CODEX_HOOK_COMMAND,
        project_root=project_root,
        servers=tuple(servers),
    )


def write_codex_config_text(project_root: Path, content: str) -> None:
    """Atomically write the Codex configuration content.

    ``newline=""`` disables platform newline translation so the bytes on disk
    equal ``content.encode("utf-8")``. That matters twice: the idempotency
    comparison and the AK3-ownership predicate both compare bytes, and with
    platform translation they would behave differently on Windows than on POSIX.

    Args:
        project_root: The target-project root.
        content: The full file content.

    Raises:
        CodexConfigError: If the path is not project-local.
    """
    path = assert_project_local_codex_config(project_root)
    atomic_write_text(path, content, newline="")


def write_codex_settings(project_root: Path) -> str | None:
    """Materialise the AK3 hook entry in ``.codex/config.toml`` (CP 8).

    Semantic, not byte-based: an existing file keeps its foreign tables, foreign
    MCP servers, unknown fields, comments and key order, and — decisively — an MCP
    registration that CP 10 merged in during an EARLIER run survives, because the
    merge only upserts and never removes. That is what makes AC 1's idempotency
    true across multiple install runs instead of only within one.

    Args:
        project_root: The target-project root.

    Returns:
        The project-relative path when the file changed, otherwise ``None``.

    Raises:
        InstallationError: When the existing configuration cannot be read or is
            structurally invalid. FAIL-CLOSED and a deliberate behaviour change:
            the previous byte comparison silently OVERWROTE an unparsable or
            user-extended file, which FK-76 §76.5.4 forbids ("unparsable TOML ...
            is a hard error without mutation").
    """
    try:
        path = assert_project_local_codex_config(project_root)
        raw = read_codex_config_bytes(project_root)
        content = render_codex_config(
            raw, hook_command=CODEX_HOOK_COMMAND, project_root=project_root, servers=()
        )
    except CodexConfigError as exc:
        raise InstallationError(
            f"Codex configuration cannot be materialised: {exc}",
            detail={"cause": "CodexConfigError", "code": str(exc.code)},
        ) from exc
    except OSError as exc:
        # The docstring promises InstallationError for unreadable configuration, so
        # a read failure (ACL change, share lock — the realistic trigger on Windows)
        # must not escape as a raw OSError and abort the engine untyped.
        raise InstallationError(
            f"Codex configuration cannot be read: {exc}",
            detail={"cause": "OSError", "path": str(codex_config_path(project_root))},
        ) from exc
    if raw is not None and raw == content.encode("utf-8"):
        return None
    write_codex_config_text(project_root, content)
    return str(path.relative_to(project_root))


def remove_codex_settings(project_root: Path) -> tuple[str, ...]:
    """Remove only Codex settings proven to be owned by AgentKit.

    The public interface remains available, but destructive authority lives in
    the detach lifecycle. Importing lazily avoids a module cycle during normal
    installer startup while ensuring this helper cannot bypass the detach-time
    owner snapshot and semantic preservation rules.
    """
    from agentkit.backend.installer.lifecycle.detach import detach_codex_config

    return detach_codex_config(project_root)


__all__ = [
    "CODEX_HOOK_COMMAND",
    "assert_project_local_codex_config",
    "build_codex_config_toml",
    "read_codex_config_bytes",
    "remove_codex_settings",
    "render_project_codex_config",
    "write_codex_config_text",
    "write_codex_settings",
]
