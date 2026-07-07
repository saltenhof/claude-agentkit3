"""CCAG installer — deploys initial CCAG rule files into target projects.

Analogous to :mod:`agentkit.backend.installer.codex_settings`, this module
writes the default CCAG rule YAML files to the target project's
``.agentkit/ccag/rules/`` directory on first install (FK-42 §42.7).

Deploy behaviour (idempotent):
- ``global.yaml``    — written once; never overwritten on re-install (F-42-036).
- ``subagents.yaml`` — written once; never overwritten on re-install.
- ``approved.yaml``  — created empty if missing; never overwritten.

Hook registration (FK-42 §42.5.2):
- For Claude Code: adds ``ccag_gatekeeper`` to ``.claude/settings.json``
  as the last ``PreToolUse`` hook.  The installer uses the canonical
  wrapper path ``agentkit-hook-claude pre ccag_gatekeeper``.
- For Codex: handled via the existing ``agentkit-hook-codex`` wrapper
  which already dispatches all pre-hooks including ``ccag_gatekeeper``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Default rule content
# ---------------------------------------------------------------------------

#: Default global.yaml — broad read/observe permissions for all agents.
DEFAULT_GLOBAL_YAML: str = """\
# global.yaml — CCAG rules for all agents (main + sub-agents).
# Applied on every hook invocation regardless of agent type (FK-42 §42.7).
#
# Rule format:
#   id:            unique identifier
#   tool:          tool name or pipe-delimited list (e.g. "Bash|Write")
#   allow_pattern: regex matched against serialised tool input -> allow
#   block_pattern: regex matched against serialised tool input -> block
#   description:   human-readable explanation
#   priority:      lower = higher priority (default: 100)

rules:
  - id: allow-read-tools
    tool: "Read|Glob|Grep"
    allow_pattern: ".*"
    description: "Allow all read-only tool operations globally"
    priority: 200
"""

#: Default subagents.yaml — narrower rights for sub-agents.
DEFAULT_SUBAGENTS_YAML: str = """\
# subagents.yaml — CCAG rules for sub-agents only (FK-42 §42.7).
# Sub-agents receive narrower rights than the main agent.
#
# These rules are loaded IN ADDITION to global.yaml for sub-agent calls.
# Block rules here take priority over allow rules in global.yaml.

rules:
  - id: deny-sub-write-claude-dir
    tool: 'Write|Edit'
    block_pattern: 'file_path:\\.claude/'
    description: 'Sub-agents may not modify .claude/ settings'
    priority: 10
    applies_to: sub

  - id: deny-sub-write-agentkit-dir
    tool: 'Write|Edit'
    block_pattern: 'file_path:\\.agentkit/'
    description: 'Sub-agents may not modify .agentkit/ config'
    priority: 10
    applies_to: sub
"""

#: Empty approved.yaml header — populated at runtime by auto-learning.
DEFAULT_APPROVED_YAML: str = """\
# approved.yaml — session-persistent CCAG approved rules (FK-42 §42.7).
# Auto-populated by the CCAG runtime when the human approves a tool call.
# Do not edit manually unless you understand the CCAG rule format.
# Fields: id, tool, allow_pattern, learned_from, learned_at, scope
"""

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CCAG_RULES_SUBDIR: str = ".agentkit/ccag/rules"
CCAG_HOOK_COMMAND_CLAUDE: str = "agentkit-hook-claude pre ccag_gatekeeper"
CCAG_HOOK_MATCHER: str = "Bash|Write|Edit|Read|Grep|Glob|Agent"


def ccag_rules_dir(project_root: Path) -> Path:
    """Return the CCAG rules directory path for a target project.

    Args:
        project_root: The root directory of the target project.

    Returns:
        Path to ``.agentkit/ccag/rules/``.
    """
    return project_root / CCAG_RULES_SUBDIR


# ---------------------------------------------------------------------------
# Deploy functions
# ---------------------------------------------------------------------------


def _write_once(path: Path, content: str) -> bool:
    """Write content to path only if the file does not already exist.

    Args:
        path: Target file path.
        content: File content to write.

    Returns:
        True when the file was written, False when it already existed.
    """
    if path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def deploy_ccag_rules(project_root: Path) -> list[str]:
    """Deploy default CCAG rule files to the target project (idempotent).

    Files are written only once and never overwritten (F-42-036).
    Returns a list of relative paths of files that were written.

    Args:
        project_root: The root directory of the target project.

    Returns:
        List of relative file paths that were written (empty when
        all files already exist).
    """
    rules_dir = ccag_rules_dir(project_root)
    written: list[str] = []

    for filename, content in [
        ("global.yaml", DEFAULT_GLOBAL_YAML),
        ("subagents.yaml", DEFAULT_SUBAGENTS_YAML),
        ("approved.yaml", DEFAULT_APPROVED_YAML),
    ]:
        path = rules_dir / filename
        if _write_once(path, content):
            written.append(str(path.relative_to(project_root)))

    return written


def build_claude_hook_entry() -> dict[str, object]:
    """Return the CCAG matcher group for ``.claude/settings.json``.

    The handler uses the canonical wrapper so CCAG is the last
    PreToolUse hook (FK-42 §42.5.2 / F-42-030).

    Returns:
        Dict with ``matcher`` and nested ``hooks`` handler list.
    """
    return {
        "matcher": CCAG_HOOK_MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": CCAG_HOOK_COMMAND_CLAUDE,
            }
        ],
    }


def build_claude_settings_snippet() -> str:
    """Return a JSON snippet showing the CCAG hook registration.

    For documentation / installer output.  The full ``.claude/settings.json``
    is managed by :mod:`agentkit.backend.installer.hooks`.

    Returns:
        Formatted JSON string for the CCAG PreToolUse hook entry.
    """
    import json

    entry = build_claude_hook_entry()
    return json.dumps(
        {
            "hooks": {
                "PreToolUse": [entry],
            }
        },
        indent=2,
    )


def deploy_ccag_settings(project_root: Path) -> list[str]:
    """Deploy CCAG rules and return a summary.

    Combined entry point for the installer.

    Args:
        project_root: The root directory of the target project.

    Returns:
        List of relative paths of files written.
    """
    return deploy_ccag_rules(project_root)


def remove_ccag_rules(project_root: Path) -> list[str]:
    """Remove deployed CCAG rule files (for uninstall).

    Removes ``global.yaml``, ``subagents.yaml``, and ``approved.yaml``.
    Does NOT remove ``approved.yaml`` if it contains user-authored rules
    (contains content beyond the header comment).

    Args:
        project_root: The root directory of the target project.

    Returns:
        List of relative paths of files removed.
    """
    rules_dir = ccag_rules_dir(project_root)
    removed: list[str] = []

    for filename in ("global.yaml", "subagents.yaml"):
        path = rules_dir / filename
        if path.exists():
            path.unlink()
            removed.append(str(path.relative_to(project_root)))

    # Only remove approved.yaml if it has no user rules
    approved = rules_dir / "approved.yaml"
    if approved.is_file():
        try:
            raw = yaml.safe_load(approved.read_text(encoding="utf-8"))
            if not raw or (isinstance(raw, list) and len(raw) == 0):
                approved.unlink()
                removed.append(str(approved.relative_to(project_root)))
        except Exception:  # noqa: BLE001
            pass  # do not remove on parse failure

    # Remove dir if empty
    if rules_dir.is_dir() and not any(rules_dir.iterdir()):
        rules_dir.rmdir()
        ccag_dir = rules_dir.parent
        if ccag_dir.is_dir() and not any(ccag_dir.iterdir()):
            ccag_dir.rmdir()

    return removed


__all__ = [
    "CCAG_HOOK_COMMAND_CLAUDE",
    "CCAG_HOOK_MATCHER",
    "CCAG_RULES_SUBDIR",
    "DEFAULT_APPROVED_YAML",
    "DEFAULT_GLOBAL_YAML",
    "DEFAULT_SUBAGENTS_YAML",
    "build_claude_hook_entry",
    "build_claude_settings_snippet",
    "ccag_rules_dir",
    "deploy_ccag_rules",
    "deploy_ccag_settings",
    "remove_ccag_rules",
]
