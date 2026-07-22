"""Surgical removal of story-knowledge-base MCP entries (AG3-176 R10).

Removes only the AgentKit-owned ``story-knowledge-base`` server from:

* target-project ``.mcp.json`` (``mcpServers`` object)
* target-project ``.codex/config.toml`` (``[mcp_servers.story-knowledge-base]``)

Foreign servers and non-MCP Codex config are value-preserved. A file is deleted
only when nothing foreign remains after the surgical strip.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agentkit.backend.installer.file_ops import atomic_write_text
from agentkit.harness_client.harness_adapters.codex_mcp_config_writer import (
    CodexMcpConfigError,
    project_codex_mcp_config_path,
)

#: MCP server key owned by AgentKit CP10 (FK-50 / AG3-175/176).
STORY_KB_SERVER_ID: Final = "story-knowledge-base"


@dataclass(frozen=True, slots=True)
class StoryKbDetachResult:
    """Outcome of surgical story-kb MCP detach."""

    mcp_json_changed: bool
    codex_changed: bool
    mcp_json_removed: bool
    codex_removed: bool
    detail: str


def detach_story_knowledge_base(project_root: Path) -> StoryKbDetachResult:
    """Surgically remove ``story-knowledge-base`` from both harness configs.

    Idempotent. Never invents defaults. Malformed files are left untouched
    (fail-safe: do not corrupt foreign config).
    """
    root = Path(project_root)
    mcp_changed, mcp_removed, mcp_detail = _detach_mcp_json(root)
    codex_changed, codex_removed, codex_detail = _detach_codex_toml(root)
    detail = f"mcp.json: {mcp_detail}; codex: {codex_detail}"
    return StoryKbDetachResult(
        mcp_json_changed=mcp_changed,
        codex_changed=codex_changed,
        mcp_json_removed=mcp_removed,
        codex_removed=codex_removed,
        detail=detail,
    )


def _detach_mcp_json(project_root: Path) -> tuple[bool, bool, str]:
    mcp_path = project_root / ".mcp.json"
    if not mcp_path.is_file():
        return False, False, "absent"
    try:
        raw = mcp_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False, False, "unreadable (left intact)"
    if not isinstance(data, dict):
        return False, False, "non-object root (left intact)"
    servers = data.get("mcpServers")
    if servers is None:
        return False, False, "no mcpServers"
    if not isinstance(servers, dict):
        return False, False, "mcpServers not object (left intact)"
    if STORY_KB_SERVER_ID not in servers:
        return False, False, "story-knowledge-base not present"
    # Surgical: drop only AK3 server; keep foreign entries value-equal.
    new_servers = {
        k: v for k, v in servers.items() if k != STORY_KB_SERVER_ID
    }
    if not new_servers:
        data.pop("mcpServers", None)
    else:
        data["mcpServers"] = new_servers
    if not data:
        mcp_path.unlink()
        return True, True, "removed file (empty after strip)"
    rendered = json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n"
    atomic_write_text(mcp_path, rendered)
    return True, False, "story-knowledge-base removed; foreign preserved"


def _detach_codex_toml(project_root: Path) -> tuple[bool, bool, str]:
    path = project_codex_mcp_config_path(project_root)
    if not path.is_file():
        return False, False, "absent"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False, False, "unreadable (left intact)"
    if "story-knowledge-base" not in text and "mcp_servers" not in text:
        return False, False, "no story-knowledge-base span"
    from agentkit.harness_client.harness_adapters.codex_mcp_config_writer import (
        surgical_remove_mcp_server,
    )

    try:
        stripped, changed = surgical_remove_mcp_server(text, STORY_KB_SERVER_ID)
    except CodexMcpConfigError:
        return False, False, "unreadable/invalid (left intact)"
    if not changed:
        return False, False, "story-knowledge-base not present"
    if not stripped.strip():
        path.unlink()
        return True, True, "removed file (empty after strip)"
    atomic_write_text(path, stripped if stripped.endswith("\n") else stripped + "\n")
    return True, False, "story-knowledge-base removed; foreign preserved"


__all__ = [
    "STORY_KB_SERVER_ID",
    "StoryKbDetachResult",
    "detach_story_knowledge_base",
]
