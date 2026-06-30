"""Level-3 project-detach (FK-10 §10.2.9, AG3-122).

Detach removes ONLY the AK3 bindings of a project and PRESERVES the project's
own code, foreign hooks and the central (canonical) project state:

* removes skill junctions — ONLY via ``unlink``/``rmdir`` after an ``isjunction``
  check, NEVER ``rmtree`` through the link (FK-43 §43.4.1.1 footgun: a recursive
  delete through a junction destroys the central bundle store);
* removes the AK3 hook blocks SURGICALLY from ``.claude/settings.json`` and
  ``.codex/hooks.json`` — only entries whose command runs through the AK3 hook
  wrapper; foreign hook blocks stay intact (an orphaned hook registration that
  points at a removed hook breaks the harness session, §10.2.9);
* removes the Project-Edge launcher (``tools/agentkit/``) and the ``.agentkit/``
  bindings.

Detach is filesystem-only. It NEVER connects to the central state backend, so it
cannot delete a higher level's canonical state (FK-10 §10.2.0 base rule).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from agentkit.backend.installer.paths import (
    AGENTKIT_DIR,
    AGENTKIT_TOOLS_DIR,
    CLAUDE_DIR,
    CODEX_DIR,
    STATIC_PROMPTS_DIR,
    STORIES_DIR,
    claude_settings_path,
    codex_config_path,
)
from agentkit.backend.skills import is_directory_link, remove_directory_link

if TYPE_CHECKING:
    from pathlib import Path

#: AK3 Claude hooks are emitted through this wrapper command (settings_writer).
AK3_CLAUDE_HOOK_WRAPPER = "agentkit-hook-claude"
#: AK3 Codex hooks are emitted through this wrapper command (settings_writer).
AK3_CODEX_HOOK_WRAPPER = "agentkit-hook-codex"

#: Substrings that uniquely identify an AK3-owned hook command. Beyond the two
#: harness wrappers, AK3 also registers hooks that invoke a script under the
#: project ``.agentkit/hooks/`` directory (e.g. ``python .agentkit/hooks/...``);
#: a FOREIGN hook never references the AK3-owned ``.agentkit/hooks`` path, so this
#: stays surgical (foreign hooks are preserved, FK-10 §10.2.9).
_AK3_HOOK_MARKERS = (
    AK3_CLAUDE_HOOK_WRAPPER,
    AK3_CODEX_HOOK_WRAPPER,
    ".agentkit/hooks",
)


def _is_ak3_hook_command(command: object) -> bool:
    """Return whether ``command`` is an AK3-owned hook command (surgical match)."""
    if not isinstance(command, str):
        return False
    normalized = command.replace("\\", "/")
    return any(marker in normalized for marker in _AK3_HOOK_MARKERS)


@dataclass(frozen=True)
class DetachResult:
    """Outcome of a project-detach (FK-10 §10.2.9).

    Attributes:
        project_root: The detached project root.
        detached_junctions: Skill junctions/symlinks detached (relative paths).
        removed_bindings: AK3 binding files/dirs removed (relative paths).
        removed_ak3_hooks: AK3 hook commands surgically removed.
        preserved_foreign_hooks: Foreign hook commands left intact.
        success: Whether the detach completed.
    """

    project_root: Path
    detached_junctions: tuple[str, ...]
    removed_bindings: tuple[str, ...]
    removed_ak3_hooks: tuple[str, ...]
    preserved_foreign_hooks: tuple[str, ...]
    success: bool = True


def detach_project(project_root: Path) -> DetachResult:
    """Detach AK3 bindings from ``project_root`` (FK-10 §10.2.9).

    Args:
        project_root: The target project root.

    Returns:
        The :class:`DetachResult` describing exactly what was detached/removed
        and which foreign hooks were preserved.

    Raises:
        FileNotFoundError: When ``project_root`` does not exist (fail-closed).
    """
    if not project_root.is_dir():
        msg = f"project root does not exist: {project_root}"
        raise FileNotFoundError(msg)

    detached_junctions = _detach_skill_junctions(project_root)
    removed_ak3, preserved = _strip_all_ak3_hooks(project_root)
    removed_bindings = _remove_ak3_bindings(project_root)

    return DetachResult(
        project_root=project_root,
        detached_junctions=tuple(detached_junctions),
        removed_bindings=tuple(removed_bindings),
        removed_ak3_hooks=tuple(removed_ak3),
        preserved_foreign_hooks=tuple(preserved),
    )


def _detach_skill_junctions(project_root: Path) -> list[str]:
    """Detach every skill junction/symlink under the harness bind points.

    Uses ``is_directory_link`` + ``remove_directory_link`` (``unlink``/``rmdir``
    after an ``isjunction`` check) so the central bundle target is never deleted
    through the link (FK-43 §43.4.1.1).
    """
    detached: list[str] = []
    for harness_dir in (CLAUDE_DIR, CODEX_DIR):
        skills_dir = project_root / harness_dir / "skills"
        if not skills_dir.is_dir():
            continue
        for entry in sorted(skills_dir.iterdir()):
            if is_directory_link(entry):
                remove_directory_link(entry)
                detached.append(str(entry.relative_to(project_root)))
    return detached


def _strip_all_ak3_hooks(project_root: Path) -> tuple[list[str], list[str]]:
    """Surgically strip AK3 hook blocks from both harness settings files."""
    removed: list[str] = []
    preserved: list[str] = []
    claude_removed, claude_kept = _strip_claude_hooks(claude_settings_path(project_root))
    codex_removed, codex_kept = _strip_codex_hooks(project_root / CODEX_DIR / "hooks.json")
    removed.extend(claude_removed)
    removed.extend(codex_removed)
    preserved.extend(claude_kept)
    preserved.extend(codex_kept)
    return removed, preserved


def _is_well_formed_claude_event(entries: object) -> bool:
    """Return whether a Claude event value is the expected list-of-blocks shape."""
    return isinstance(entries, list) and all(isinstance(e, dict) for e in entries)


def _strip_claude_hooks(settings_path: Path) -> tuple[list[str], list[str]]:
    """Remove AK3 entries from ``.claude/settings.json`` (two-level shape).

    Keeps foreign hook entries and any non-``hooks`` settings keys. Fail-closed
    against an unexpected/malformed shape (mirrors the harness settings-writer
    contract, ``settings_writer._coerce_hooks_section``): a present-but-malformed
    ``hooks`` section (``hooks`` not an object, or an event value that is not a
    well-formed list-of-blocks) is PRESERVED VERBATIM and never popped/rewritten —
    coercing it to empty would DELETE foreign hook config (FK-10 §10.2.9). Only
    recognized AK3 blocks in well-formed lists are stripped. The file is removed
    only when it is left structurally empty by a clean strip.
    """
    settings = _load_json_object(settings_path)
    if settings is None:
        return [], []
    if "hooks" not in settings:
        return [], []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        # Present but malformed top-level shape: preserve verbatim, no rewrite.
        return [], []
    removed: list[str] = []
    preserved: list[str] = []
    new_hooks: dict[str, object] = {}
    for event_key, entries in hooks.items():
        if not _is_well_formed_claude_event(entries):
            # Unexpected shape for this event: preserve verbatim, strip nothing.
            new_hooks[event_key] = entries
            continue
        kept_entries = [
            entry
            for entry in cast("list[dict[str, object]]", entries)
            if not _record_ak3_command(entry.get("command", ""), removed, preserved)
        ]
        if kept_entries:
            new_hooks[event_key] = kept_entries
    if new_hooks:
        settings["hooks"] = new_hooks
    else:
        settings.pop("hooks", None)
    _persist_or_remove(settings_path, settings)
    return removed, preserved


def _strip_codex_hooks(hooks_path: Path) -> tuple[list[str], list[str]]:
    """Remove AK3 handlers from ``.codex/hooks.json`` (three-level shape).

    Foreign matcher groups and foreign handlers within a shared group are
    preserved; an emptied AK3-only group/event is dropped. Fail-closed against an
    unexpected/malformed shape (mirrors ``settings_writer._coerce_hooks_section``):
    a present-but-malformed ``hooks`` section (``hooks`` not an object, an event
    value that is not a list, a group/handler of an unexpected shape) is PRESERVED
    VERBATIM and never popped/rewritten — coercing it would DELETE foreign hook
    config (FK-10 §10.2.9). The file is removed only when a clean strip leaves it
    structurally empty.
    """
    settings = _load_json_object(hooks_path)
    if settings is None:
        return [], []
    if "hooks" not in settings:
        return [], []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        # Present but malformed top-level shape: preserve verbatim, no rewrite.
        return [], []
    removed: list[str] = []
    preserved: list[str] = []
    new_hooks: dict[str, object] = {}
    for event_key, groups in hooks.items():
        if not isinstance(groups, list):
            # Malformed event value: preserve verbatim, strip nothing.
            new_hooks[event_key] = groups
            continue
        kept_groups = _strip_codex_groups(groups, removed, preserved)
        if kept_groups:
            new_hooks[event_key] = kept_groups
    if new_hooks:
        settings["hooks"] = new_hooks
    else:
        settings.pop("hooks", None)
    _persist_or_remove(hooks_path, settings)
    return removed, preserved


def _strip_codex_groups(
    groups: list[object], removed: list[str], preserved: list[str]
) -> list[object]:
    """Filter AK3 handlers out of a Codex event's matcher groups (helper).

    A malformed group (not an object, ``hooks`` not a list, or a non-object
    handler) is PRESERVED VERBATIM — never coerced/dropped, which would delete
    foreign config (FK-10 §10.2.9).
    """
    kept_groups: list[object] = []
    for group in groups:
        handlers = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(group, dict) or not _is_well_formed_codex_handlers(handlers):
            # Foreign/malformed group shape: preserve verbatim.
            kept_groups.append(group)
            continue
        kept_handlers = [
            handler
            for handler in cast("list[dict[str, object]]", handlers)
            if not _record_ak3_command(handler.get("command", ""), removed, preserved)
        ]
        if kept_handlers:
            group["hooks"] = kept_handlers
            kept_groups.append(group)
    return kept_groups


def _is_well_formed_codex_handlers(handlers: object) -> bool:
    """Return whether a Codex group's ``hooks`` value is a list of handler objects."""
    return isinstance(handlers, list) and all(isinstance(h, dict) for h in handlers)


def _record_ak3_command(
    command: object, removed: list[str], preserved: list[str]
) -> bool:
    """Classify a hook command; record it and return whether it is AK3-owned."""
    if _is_ak3_hook_command(command):
        removed.append(str(command))
        return True
    preserved.append(str(command))
    return False


def _remove_ak3_bindings(project_root: Path) -> list[str]:
    """Remove the remaining AK3 binding artifacts (launcher, ``.agentkit/``, etc.).

    Each tree removal is guarded against a junction so a stray reparse point is
    detached, never recursed through (FK-43 §43.4.1.1).
    """
    removed: list[str] = []
    removed.extend(_remove_file(codex_config_path(project_root), project_root))
    removed.extend(_safe_remove_tree(project_root / AGENTKIT_TOOLS_DIR, project_root))
    removed.extend(_remove_empty_dir(project_root / "tools", project_root))
    removed.extend(_safe_remove_tree(project_root / AGENTKIT_DIR, project_root))
    removed.extend(_safe_remove_tree(project_root / STATIC_PROMPTS_DIR, project_root))
    removed.extend(_remove_empty_dir(project_root / CLAUDE_DIR / "context", project_root))
    removed.extend(_remove_empty_dir(project_root / CLAUDE_DIR / "skills", project_root))
    removed.extend(_remove_empty_dir(project_root / CODEX_DIR / "skills", project_root))
    removed.extend(_remove_empty_dir(project_root / CLAUDE_DIR, project_root))
    removed.extend(_remove_empty_dir(project_root / CODEX_DIR, project_root))
    removed.extend(_remove_empty_dir(project_root / STORIES_DIR, project_root))
    return removed


def _load_json_object(path: Path) -> dict[str, object] | None:
    """Load a JSON object from ``path`` or ``None`` when the file is absent.

    A present-but-malformed file is left untouched (``None``) so detach never
    corrupts a foreign-owned settings file it cannot parse.
    """
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _persist_or_remove(path: Path, settings: dict[str, object]) -> None:
    """Rewrite the settings file, or remove it when it is left empty."""
    if settings:
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    elif path.is_file():
        path.unlink()


def _remove_file(path: Path, project_root: Path) -> list[str]:
    """Remove a single file when present."""
    if not path.is_file():
        return []
    path.unlink()
    return [str(path.relative_to(project_root))]


def _safe_remove_tree(path: Path, project_root: Path) -> list[str]:
    """Remove a directory tree, detaching (never recursing through) a junction."""
    if is_directory_link(path):
        remove_directory_link(path)
        return [str(path.relative_to(project_root))]
    if not path.exists():
        return []
    shutil.rmtree(path)
    return [str(path.relative_to(project_root))]


def _remove_empty_dir(path: Path, project_root: Path) -> list[str]:
    """Remove a directory only when it exists and is empty."""
    if not path.is_dir() or any(path.iterdir()):
        return []
    path.rmdir()
    return [str(path.relative_to(project_root))]


__all__ = [
    "AK3_CLAUDE_HOOK_WRAPPER",
    "AK3_CODEX_HOOK_WRAPPER",
    "DetachResult",
    "detach_project",
]
