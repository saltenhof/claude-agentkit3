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

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from agentkit.backend.installer.codex_settings import build_codex_config_toml
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

#: Structural keys of a hook matcher group. Any OTHER key is foreign-owned data
#: that must survive even when the group's AK3 handler list is fully stripped
#: (FK-10 §10.2.9 surgical removal — never discard foreign config).
_MATCHER_GROUP_STRUCTURAL_KEYS = frozenset({"matcher", "hooks"})


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
        preserved_foreign_files: Files left intact because their content is not
            the unmodified AK3-deployed content (a user-modified prompt template
            or a ``.codex/config.toml`` carrying foreign config); relative paths.
        success: Whether the detach completed.
    """

    project_root: Path
    detached_junctions: tuple[str, ...]
    removed_bindings: tuple[str, ...]
    removed_ak3_hooks: tuple[str, ...]
    preserved_foreign_hooks: tuple[str, ...]
    preserved_foreign_files: tuple[str, ...] = ()
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
    preserved_files: list[str] = []
    # AG3-176 R10: surgical dual-harness MCP strip BEFORE wholesale binding
    # removal so story-knowledge-base never survives a "foreign/modified" Codex
    # file that dual-write extended beyond build_codex_config_toml().
    mcp_removed = _detach_story_kb_mcp(project_root, preserved_files)
    removed_bindings = mcp_removed + _remove_ak3_bindings(project_root, preserved_files)

    return DetachResult(
        project_root=project_root,
        detached_junctions=tuple(detached_junctions),
        removed_bindings=tuple(removed_bindings),
        removed_ak3_hooks=tuple(removed_ak3),
        preserved_foreign_hooks=tuple(preserved),
        preserved_foreign_files=tuple(preserved_files),
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


def _strip_claude_hooks(settings_path: Path) -> tuple[list[str], list[str]]:
    """Remove AK3 handlers from ``.claude/settings.json`` (three-level shape).

    Keeps foreign matcher groups, handlers and any non-``hooks`` settings keys. Fail-closed
    against an unexpected/malformed shape (mirrors the harness settings-writer
    contract, ``settings_writer._coerce_hooks_section``): a present-but-malformed
    ``hooks`` section (``hooks`` not an object, or an event value that is not a
    well-formed list of matcher groups) is PRESERVED VERBATIM and never
    popped/rewritten — coercing it to empty would DELETE foreign hook config
    (FK-10 §10.2.9). Only recognized AK3 handlers in well-formed lists are
    stripped. The file is removed only when it is left structurally empty by a
    clean strip.
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
    for event_key, groups in hooks.items():
        if not isinstance(groups, list):
            # Unexpected shape for this event: preserve verbatim, strip nothing.
            new_hooks[event_key] = groups
            continue
        kept_groups = _strip_hook_matcher_groups(groups, removed, preserved)
        if kept_groups:
            new_hooks[event_key] = kept_groups
    if not removed:
        # No AK3 hook was found: the strip changed nothing. Leave the file
        # byte-for-byte untouched (never rewrite a purely-foreign settings file —
        # surgical, only AK3 bindings, FK-10 §10.2.9).
        return [], preserved
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
        kept_groups = _strip_hook_matcher_groups(groups, removed, preserved)
        if kept_groups:
            new_hooks[event_key] = kept_groups
    if not removed:
        # No AK3 handler was found: the strip changed nothing. Leave the file
        # byte-for-byte untouched (never rewrite a purely-foreign hooks file —
        # surgical, only AK3 bindings, FK-10 §10.2.9).
        return [], preserved
    if new_hooks:
        settings["hooks"] = new_hooks
    else:
        settings.pop("hooks", None)
    _persist_or_remove(hooks_path, settings)
    return removed, preserved


def _strip_hook_matcher_groups(
    groups: list[object], removed: list[str], preserved: list[str]
) -> list[object]:
    """Filter AK3 handlers out of an event's matcher groups (helper).

    A malformed group (not an object, ``hooks`` not a list, or a non-object
    handler) is PRESERVED VERBATIM — never coerced/dropped, which would delete
    foreign config (FK-10 §10.2.9).
    """
    kept_groups: list[object] = []
    for group in groups:
        handlers = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(group, dict) or not _is_well_formed_hook_handlers(handlers):
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
        elif _group_has_foreign_keys(group):
            # All handlers were AK3, but the group carries foreign sibling keys
            # beyond the structural ``matcher``/``hooks`` (e.g. a foreign ``note``).
            # Keep the foreign data but leave a schema-VALID empty ``hooks`` LIST
            # rather than popping the key: the Codex settings writer
            # (settings_writer._validate_group_shape) fails closed on a group
            # without a ``hooks`` list, so a popped key would break a later hook
            # registration/reinstall on the preserved file (FK-10 §10.2.9 surgical
            # removal — never discard foreign config, never leave it schema-invalid).
            group["hooks"] = []
            kept_groups.append(group)
    return kept_groups


def _group_has_foreign_keys(group: dict[str, object]) -> bool:
    """Return whether a matcher group carries keys beyond the AK3 structure.

    A pure AK3 registration group has only the structural ``matcher``/``hooks``
    keys; any other key is foreign-owned data that must survive an emptied strip.
    """
    return any(key not in _MATCHER_GROUP_STRUCTURAL_KEYS for key in group)


def _is_well_formed_hook_handlers(handlers: object) -> bool:
    """Return whether a matcher group's ``hooks`` value is a list of handlers."""
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


def _detach_story_kb_mcp(project_root: Path, preserved_files: list[str]) -> list[str]:
    """Surgically remove story-knowledge-base from ``.mcp.json`` + Codex TOML.

    AG3-176 R10 / AG3-175 surgical merge symmetry: only the AK3-owned server
    is removed; foreign MCP servers and non-MCP Codex keys stay value-equal.
    Files deleted only when empty of foreign content after strip.
    """
    from agentkit.backend.installer.mcp_registration.detach_story_kb import (
        detach_story_knowledge_base,
    )

    result = detach_story_knowledge_base(project_root)
    removed: list[str] = []
    mcp_path = project_root / ".mcp.json"
    codex_path = project_root / CODEX_DIR / "config.toml"
    if result.mcp_json_removed:
        removed.append(str(mcp_path.relative_to(project_root)))
    elif result.mcp_json_changed and mcp_path.is_file():
        removed.append(f"{mcp_path.relative_to(project_root)}#story-knowledge-base")
    if result.codex_removed:
        removed.append(str(codex_path.relative_to(project_root)))
    elif result.codex_changed and codex_path.is_file():
        # Foreign content remains; report surgical strip, not full delete.
        removed.append(f"{codex_path.relative_to(project_root)}#story-knowledge-base")
        if str(codex_path.relative_to(project_root)) not in preserved_files:
            # Mark that foreign residual may still exist for later binding pass.
            pass
    return removed


def _remove_ak3_bindings(project_root: Path, preserved_files: list[str]) -> list[str]:
    """Remove the remaining AK3 binding artifacts (launcher, ``.agentkit/``, etc.).

    Each tree removal is guarded against a junction so a stray reparse point is
    detached, never recursed through (FK-43 §43.4.1.1). Files whose content is not
    the unmodified AK3-deployed content (a foreign ``.codex/config.toml`` or a
    user-modified prompt template) are preserved and reported via
    ``preserved_files`` instead of being deleted (FK-10 §10.2.9, "preserve project
    code").
    """
    removed: list[str] = []
    # Codex config: after surgical MCP strip, only delete when byte-equal to the
    # bare AK3 base (no foreign residual). Foreign residual is preserved.
    removed.extend(_remove_ak3_codex_config(project_root, preserved_files))
    removed.extend(_safe_remove_tree(project_root / AGENTKIT_TOOLS_DIR, project_root))
    removed.extend(_remove_empty_dir(project_root / "tools", project_root))
    removed.extend(_safe_remove_tree(project_root / AGENTKIT_DIR, project_root))
    removed.extend(_remove_ak3_prompt_bindings(project_root, preserved_files))
    removed.extend(_remove_empty_dir(project_root / CLAUDE_DIR / "context", project_root))
    removed.extend(_remove_empty_dir(project_root / CLAUDE_DIR / "skills", project_root))
    removed.extend(_remove_empty_dir(project_root / CODEX_DIR / "skills", project_root))
    removed.extend(_remove_empty_dir(project_root / CLAUDE_DIR, project_root))
    removed.extend(_remove_empty_dir(project_root / CODEX_DIR, project_root))
    removed.extend(_remove_empty_dir(project_root / STORIES_DIR, project_root))
    return removed


def _remove_ak3_codex_config(project_root: Path, preserved_files: list[str]) -> list[str]:
    """Remove ``.codex/config.toml`` when only AK3-owned content remains.

    After surgical MCP strip (AG3-176 R10), the file may still hold the AK3
    hook block from ``build_codex_config_toml``. Remove when:

    * byte-equal to that builder output, or
    * only whitespace remains, or
    * only the AK3 hook command remains (no foreign tables).

    A file extended with foreign Codex config is PRESERVED (reported via
    ``preserved_files``) rather than deleted wholesale (FK-10 §10.2.9).
    """
    config_path = codex_config_path(project_root)
    if not config_path.is_file():
        return []
    try:
        current = config_path.read_text(encoding="utf-8")
    except OSError:
        current = None
    if current is None:
        return []
    base = build_codex_config_toml()
    stripped = current.strip()
    # Delete only when the residual is exactly the AK3-managed hook block (or
    # empty). Any extra table (e.g. ``[user.custom]``) or foreign key is
    # foreign residual and must be preserved (FK-10 §10.2.9). The previous
    # ``count("[") <= 2`` heuristic falsely treated one foreign table as AK3-only.
    only_ak3_hook = stripped == base.strip() or stripped == ""
    if not only_ak3_hook:
        preserved_files.append(str(config_path.relative_to(project_root)))
        return []
    return _remove_file(config_path, project_root)


def _remove_ak3_prompt_bindings(project_root: Path, preserved_files: list[str]) -> list[str]:
    """Remove the AK3-deployed prompt templates + manifest, preserving foreign files.

    Install (``runner._deploy_prompt_bindings``) hardlinks the prompt-bundle
    ``manifest.json`` plus, for every ``templates`` entry, a file named
    ``Path(relpath).name`` into ``project_root/prompts/``; each manifest entry also
    carries the ``sha256`` of the deployed file's bytes (``runner._file_digests``:
    ``hashlib.sha256(file_bytes).hexdigest()``). Detach recovers EXACTLY that
    AK3-owned set from the deployed manifest and removes a template ONLY when its
    current content's sha256 still matches the manifest digest — proving it is the
    unmodified AK3-deployed file. A user-MODIFIED template (digest mismatch) or a
    foreign file colliding with an AK3 basename therefore SURVIVES and is reported
    as preserved (FK-10 §10.2.9 surgical removal, "preserve project code").

    Fail-safe (D4): when the manifest is missing or cannot be parsed into the
    expected ``{templates: {...}}`` shape, NOTHING is removed from ``prompts/`` —
    the directory and the manifest stay intact (an unreadable manifest is never a
    licence to delete).
    """
    prompts_dir = project_root / STATIC_PROMPTS_DIR
    if not prompts_dir.is_dir():
        return []
    manifest_path = prompts_dir / _prompt_manifest_filename()
    expected = _ak3_prompt_template_digests(manifest_path)
    if expected is None:
        # Missing/malformed/unreadable manifest: fail safe, touch nothing.
        return []
    removed: list[str] = []
    for name, digest in expected.items():
        template_path = prompts_dir / name
        if _file_sha256_matches(template_path, digest):
            removed.extend(_remove_file(template_path, project_root))
        elif template_path.is_file():
            # Modified AK3 template or a foreign file colliding with the basename:
            # the digest no longer matches the deployed content, so preserve it.
            preserved_files.append(str(template_path.relative_to(project_root)))
    # The manifest's AK3 set is now removed-or-accounted-for: drop the manifest,
    # then remove ``prompts/`` only when a clean strip leaves it empty.
    removed.extend(_remove_file(manifest_path, project_root))
    removed.extend(_remove_empty_dir(prompts_dir, project_root))
    return removed


def _file_sha256_matches(path: Path, expected_digest: str) -> bool:
    """Return whether ``path`` exists and its bytes hash to ``expected_digest``.

    Reuses the installer's hashing (``runner._file_digests`` /
    ``_prompt_template_digests``): the manifest ``sha256`` is
    ``hashlib.sha256(file_bytes).hexdigest()`` over the raw file bytes, so an
    unmodified AK3-deployed template matches and a modified/foreign one does not.
    """
    if not path.is_file():
        return False
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return False
    return digest == expected_digest


def _prompt_manifest_filename() -> str:
    """Return the install-owned prompt-bundle manifest filename (single source).

    Reuses the installer's constant so detach and install agree on the deployed
    manifest name without a duplicated literal (lazy import avoids a module-load
    cycle; ``runner`` itself imports ``detach`` lazily for teardown).
    """
    from agentkit.backend.installer.runner import PROMPT_MANIFEST_FILENAME

    return PROMPT_MANIFEST_FILENAME


def _ak3_prompt_template_digests(manifest_path: Path) -> dict[str, str] | None:
    """Return ``{deployed_basename: sha256}`` from the deployed manifest, or ``None``.

    Mirrors ``runner._deploy_prompt_bindings`` / ``runner._prompt_template_digests``:
    each well-formed ``templates`` entry deploys a file named ``Path(relpath).name``
    and carries that file's ``sha256``. Returns the basename->digest map when EVERY
    entry carries BOTH a usable ``relpath`` and a non-empty ``sha256``.

    Returns ``None`` (D4 fail-safe) when the manifest is missing, unreadable, not a
    JSON object, lacks the expected ``templates`` object, OR carries ANY malformed
    entry (an entry that is not an object, or one missing/empty/non-str ``relpath``
    or ``sha256``). A partial digest map would let the caller remove the valid
    templates AND drop ``prompts/manifest.json`` while real content next to a single
    malformed entry slips through — D4 requires "malformed -> remove nothing", so an
    untrustworthy manifest is never a licence to delete (an unreadable manifest is
    never a licence to delete).
    """
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(manifest, dict):
        return None
    templates = manifest.get("templates")
    if not isinstance(templates, dict):
        return None
    digests: dict[str, str] = {}
    for entry in templates.values():
        if not isinstance(entry, dict):
            return None
        relpath = entry.get("relpath")
        sha256 = entry.get("sha256")
        if not (isinstance(relpath, str) and relpath):
            return None
        if not (isinstance(sha256, str) and sha256):
            return None
        digests[Path(relpath).name] = sha256
    return digests


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
