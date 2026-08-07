"""Install the CCAG hook registration without permission-rule authority."""

from __future__ import annotations

from pathlib import Path

from agentkit.backend.boundary.filesystem import assert_project_local_file_path
from agentkit.backend.governance.hook_registration import HookId
from agentkit_wire.governance_registration import HookDefinition, HookEventName

_CCAG_HOOK_WRAPPER = "agentkit-hook-claude"
CCAG_HOOK_MATCHER = "Bash|Write|Edit|Read|Grep|Glob|Agent"
_OBSOLETE_PERMISSION_RULE_PATHS: tuple[str, ...] = (
    ".agentkit/ccag/rules/global.yaml",
    ".agentkit/ccag/rules/subagents.yaml",
    ".agentkit/ccag/rules/approved.yaml",
)


def build_ccag_hook_definition() -> HookDefinition:
    """Build the logical matcher-only definition for governance registration."""
    return HookDefinition(
        hook_event_name=HookEventName.PRE_TOOL_USE,
        matcher=CCAG_HOOK_MATCHER,
        command=f"{_CCAG_HOOK_WRAPPER} pre {HookId.CCAG_GATEKEEPER.value}",
    )


def build_installed_hook_definitions() -> list[HookDefinition]:
    """Return the single complete default set used by install and upgrade."""
    from agentkit.backend.governance.default_hook_definitions import (
        build_default_hook_definitions,
    )

    definitions = build_default_hook_definitions()
    definitions.append(build_ccag_hook_definition())
    return definitions


def remove_obsolete_permission_rule_files(project_root: Path) -> list[str]:
    """Remove permission-rule files left by an earlier installation.

    The files no longer have a productive reader or authority. They are removed
    unconditionally, including previously human-authored approvals, so an upgrade
    cannot leave an apparently effective permission policy behind.
    """
    file_paths = [
        (relative, assert_project_local_file_path(project_root, Path(relative)))
        for relative in _OBSOLETE_PERMISSION_RULE_PATHS
    ]
    directory_paths = [
        assert_project_local_file_path(project_root, relative_directory)
        for relative_directory in (
            Path(".agentkit") / "ccag" / "rules",
            Path(".agentkit") / "ccag",
        )
    ]

    removed: list[str] = []
    for relative, path in file_paths:
        if not path.is_file():
            continue
        path.unlink()
        removed.append(relative)

    for directory in directory_paths:
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    return removed


__all__ = [
    "CCAG_HOOK_MATCHER",
    "build_ccag_hook_definition",
    "build_installed_hook_definitions",
    "remove_obsolete_permission_rule_files",
]
