"""Codex harness settings installed into target projects.

The official AgentKit Codex hook entrypoint is the console script
``agentkit-hook-codex``.  Target projects receive a project-local
``.codex/config.toml`` so Codex can call that adapter without changing the
Claude-Code hook path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.installer.file_ops import atomic_write_text
from agentkit.backend.installer.paths import CODEX_DIR, codex_config_path

if TYPE_CHECKING:
    from pathlib import Path

CODEX_HOOK_COMMAND = "agentkit-hook-codex"


def build_codex_config_toml() -> str:
    """Return the AgentKit-managed Codex hook configuration."""

    return (
        "# AgentKit-managed Codex hook configuration.\n"
        "[hooks.pre_tool_use]\n"
        f'command = "{CODEX_HOOK_COMMAND}"\n'
    )


def write_codex_settings(project_root: Path) -> str | None:
    """Write ``.codex/config.toml`` if it is missing or lacks the AK3 hook.

    Surgical (AG3-175/176): when the file already contains the AgentKit hook
    command, leave the full document untouched so dual-write MCP tables
    (``[mcp_servers.story-knowledge-base]``) are never clobbered on re-install.

    Returns:
        The relative path when the file changed, otherwise ``None``.
    """

    config_path = codex_config_path(project_root)
    content = build_codex_config_toml()
    if config_path.is_file():
        try:
            current = config_path.read_text(encoding="utf-8")
        except OSError:
            current = ""
        if current == content:
            return None
        # Already has the AK3 hook entry — do not overwrite foreign / MCP spans.
        if CODEX_HOOK_COMMAND in current and "[hooks.pre_tool_use]" in current:
            return None
    atomic_write_text(config_path, content)
    return str(config_path.relative_to(project_root))


def remove_codex_settings(project_root: Path) -> tuple[str, ...]:
    """Remove the AgentKit Codex settings file and empty parent directory."""

    removed: list[str] = []
    config_path = codex_config_path(project_root)
    if config_path.exists():
        config_path.unlink()
        removed.append(str(config_path.relative_to(project_root)))

    codex_dir = project_root / CODEX_DIR
    if codex_dir.is_dir() and not any(codex_dir.iterdir()):
        codex_dir.rmdir()
        removed.append(CODEX_DIR)

    return tuple(removed)


__all__ = [
    "CODEX_HOOK_COMMAND",
    "build_codex_config_toml",
    "remove_codex_settings",
    "write_codex_settings",
]
