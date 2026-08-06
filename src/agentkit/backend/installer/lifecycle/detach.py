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
import shlex
import shutil
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

from agentkit.backend.boundary.filesystem import (
    FilesystemContainmentError,
    assert_project_local_file_path,
    matches_resolved_interpreter_owner,
    matches_resolved_path_owner,
)
from agentkit.backend.core_types.mcp_server_registration import (
    ARE_MCP_SERVER,
    ARE_MCP_WRAPPER_NAME,
    CODEX_HOOK_WRAPPER_NAME,
    STORY_KNOWLEDGE_BASE_SERVER,
)
from agentkit.backend.installer.interpreter import (
    render_resolved_command,
    resolve_ak3_interpreter,
    resolve_ak3_wrapper,
)
from agentkit.backend.installer.mcp_registration import render_mcp_json_without_ak3
from agentkit.backend.installer.paths import (
    AGENTKIT_DIR,
    AGENTKIT_TOOLS_DIR,
    CLAUDE_DIR,
    CODEX_DIR,
    STATIC_PROMPTS_DIR,
    claude_settings_path,
    codex_config_path,
)
from agentkit.backend.skills import is_directory_link, remove_directory_link
from agentkit.harness_client.harness_adapters.codex_config_toml import (
    CodexConfigError,
    render_without_ak3,
)

#: AK3 Claude hooks are emitted through this wrapper (settings_writer).
AK3_CLAUDE_HOOK_WRAPPER = "agentkit-hook-claude"
#: AK3 Codex hooks are emitted through this wrapper (settings_writer).
AK3_CODEX_HOOK_WRAPPER = "agentkit-hook-codex"
_AK3_HOOK_WRAPPER_EXECUTABLES = frozenset(
    {
        AK3_CLAUDE_HOOK_WRAPPER,
        AK3_CODEX_HOOK_WRAPPER,
        f"{AK3_CLAUDE_HOOK_WRAPPER}.exe",
        f"{AK3_CODEX_HOOK_WRAPPER}.exe",
    }
)

#: Structural keys of a hook matcher group. Any OTHER key is foreign-owned data
#: that must survive even when the group's AK3 handler list is fully stripped
#: (FK-10 §10.2.9 surgical removal — never discard foreign config).
_MATCHER_GROUP_STRUCTURAL_KEYS = frozenset({"matcher", "hooks"})


def _is_ak3_hook_command(
    command: object,
    *,
    project_root: Path,
    resolved_command_owners: Mapping[str, str],
) -> bool:
    """Return whether ``command`` is an AK3-owned hook command.

    Ownership is decided on the command's TOKENS, not on a substring of the
    whole line. A foreign hook that merely mentions an AK3 name --
    ``echo "agentkit-hook-codex" && ./foreign-quality-gate`` -- was removed by
    detach; a foreign backup path ``/opt/.agentkit/hooks-backup/quality.sh``
    counted as ours because it contains ``.agentkit/hooks``. Detach deletes what
    it matches, so a wrong match destroys foreign configuration.
    """
    if not isinstance(command, str):
        return False
    try:
        tokens = shlex.split(command.replace("\\", "/"), posix=True)
    except ValueError:
        return False  # unparsable shell is not provably ours -- keep it
    if not tokens:
        return False
    # A shell operator starts a NEW command; anything after one is somebody
    # else's. `echo "agentkit-hook-codex" && ./foreign-gate` is a foreign hook
    # that merely prints our name, and detach deletes what it matches.
    if any(token in {"&&", "||", ";", "|", "&"} for token in tokens):
        return False
    executed = tokens[0]
    executable_name = executed.rsplit("/", maxsplit=1)[-1].lower()
    executable_is_absolute = executed.startswith("/") or (
        len(executed) >= 3 and executed[1] == ":" and executed[2] == "/"
    )
    if executable_is_absolute and executable_name in _AK3_HOOK_WRAPPER_EXECUTABLES:
        wrapper_name = executable_name.removesuffix(".exe")
        return matches_resolved_path_owner(
            executed,
            resolved_command_owners.get(wrapper_name),
        )
    # The bundled target-project settings register the project-local script
    # through the central interpreter. Only PYTHON is modelled: a
    # flag grammar shared across python, bash, node and pwsh does not exist
    # (`node -e` and `pwsh -Command` take code, not a path), and guessing one
    # made detach delete foreign hooks. What no producer writes is not claimed.
    if executable_name not in _PYTHON_INTERPRETERS:
        return False
    if not matches_resolved_interpreter_owner(
        executed,
        resolved_command_owners.get(STORY_KNOWLEDGE_BASE_SERVER),
    ):
        return False
    script = _python_script_argument(tokens[1:])
    return script is not None and _is_ak3_hooks_path(script, project_root=project_root)


#: Interpreter basenames used for current absolute hooks and older bare text.
#: This parser vocabulary never launches or selects an interpreter.
_PYTHON_INTERPRETERS = frozenset({"python", "python3", "python.exe", "python3.exe"})
#: Python options that consume the NEXT argument -- it is not the script.
_PYTHON_VALUE_OPTIONS = frozenset({"-W", "-X", "--check-hash-based-pycs"})
#: Python options after which no script path follows: the code is inline.
_PYTHON_INLINE_OPTIONS = frozenset({"-c", "-m"})


def _is_ak3_hooks_path(token: str, *, project_root: Path) -> bool:
    """Whether ``token`` stays inside this project's AK3 hooks directory.

    Relative script arguments are interpreted from the project root, matching
    the hook producer's working-directory contract. The shared R1 ownership
    proof rejects symlinks before ``..`` normalisation and ensures that an
    absolute lookalike in another project's ``.agentkit/hooks`` tree is foreign.
    """
    absolute_project = (
        project_root if project_root.is_absolute() else Path.cwd() / project_root
    )
    script_path = Path(token)
    candidate = (
        script_path if script_path.is_absolute() else absolute_project / script_path
    )
    hooks_owner = absolute_project / AGENTKIT_DIR / "hooks"
    return matches_resolved_path_owner(
        str(candidate),
        str(hooks_owner),
        allow_descendants=True,
    ) and not matches_resolved_path_owner(str(candidate), str(hooks_owner))


def _python_script_argument(arguments: list[str]) -> str | None:
    """Return the path python EXECUTES, or ``None`` if it executes no file.

    ``python -c <text>`` runs the text as code and ``python -m <name>`` treats
    it as a module; neither runs the file. ``python -W ignore <path>`` and
    ``python -O <path>`` both do -- ``-O`` is a boolean switch and must not
    swallow the script, which is how an AK3 hook was left behind on detach.
    """
    remaining = list(arguments)
    while remaining:
        token = remaining.pop(0)
        if token in _PYTHON_INLINE_OPTIONS:
            return None
        if token in _PYTHON_VALUE_OPTIONS:
            if remaining:
                remaining.pop(0)
            continue
        if token.startswith("-"):
            continue  # boolean switch such as -O, -B, -u
        return token
    return None


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

    resolved_command_owners = _resolved_detach_command_owners()
    detached_junctions = _detach_skill_junctions(project_root)
    removed_ak3, preserved = _strip_all_ak3_hooks(
        project_root,
        resolved_command_owners=resolved_command_owners,
    )
    preserved_files: list[str] = []
    removed_bindings = _remove_ak3_bindings(
        project_root,
        preserved_files,
        resolved_command_owners=resolved_command_owners,
    )

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
        removed_from_bind_point = False
        for entry in sorted(skills_dir.iterdir()):
            if is_directory_link(entry):
                remove_directory_link(entry)
                detached.append(str(entry.relative_to(project_root)))
                removed_from_bind_point = True
        if (
            removed_from_bind_point
            and not is_directory_link(skills_dir)
            and not any(skills_dir.iterdir())
        ):
            skills_dir.rmdir()
            harness_path = project_root / harness_dir
            if (
                not is_directory_link(harness_path)
                and harness_path.is_dir()
                and not any(harness_path.iterdir())
            ):
                harness_path.rmdir()
    return detached


def _strip_all_ak3_hooks(
    project_root: Path,
    *,
    resolved_command_owners: Mapping[str, str],
) -> tuple[list[str], list[str]]:
    """Surgically strip AK3 hook blocks from both harness settings files."""
    removed: list[str] = []
    preserved: list[str] = []
    claude_removed, claude_kept = _strip_claude_hooks(
        claude_settings_path(project_root),
        project_root=project_root,
        resolved_command_owners=resolved_command_owners,
    )
    codex_removed, codex_kept = _strip_codex_hooks(
        project_root / CODEX_DIR / "hooks.json",
        project_root=project_root,
        resolved_command_owners=resolved_command_owners,
    )
    removed.extend(claude_removed)
    removed.extend(codex_removed)
    preserved.extend(claude_kept)
    preserved.extend(codex_kept)
    return removed, preserved


def _strip_claude_hooks(
    settings_path: Path,
    *,
    project_root: Path,
    resolved_command_owners: Mapping[str, str],
) -> tuple[list[str], list[str]]:
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
        kept_groups = _strip_hook_matcher_groups(
            groups,
            removed,
            preserved,
            project_root=project_root,
            resolved_command_owners=resolved_command_owners,
        )
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


def _strip_codex_hooks(
    hooks_path: Path,
    *,
    project_root: Path,
    resolved_command_owners: Mapping[str, str],
) -> tuple[list[str], list[str]]:
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
        kept_groups = _strip_hook_matcher_groups(
            groups,
            removed,
            preserved,
            project_root=project_root,
            resolved_command_owners=resolved_command_owners,
        )
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
    groups: list[object],
    removed: list[str],
    preserved: list[str],
    *,
    project_root: Path,
    resolved_command_owners: Mapping[str, str],
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
            if not _record_ak3_command(
                handler.get("command", ""),
                removed,
                preserved,
                project_root=project_root,
                resolved_command_owners=resolved_command_owners,
            )
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
    command: object,
    removed: list[str],
    preserved: list[str],
    *,
    project_root: Path,
    resolved_command_owners: Mapping[str, str],
) -> bool:
    """Classify a hook command; record it and return whether it is AK3-owned."""
    if _is_ak3_hook_command(
        command,
        project_root=project_root,
        resolved_command_owners=resolved_command_owners,
    ):
        removed.append(str(command))
        return True
    preserved.append(str(command))
    return False


def _remove_ak3_bindings(
    project_root: Path,
    preserved_files: list[str],
    *,
    resolved_command_owners: Mapping[str, str],
) -> list[str]:
    """Remove the remaining AK3 binding artifacts (launcher, ``.agentkit/``, etc.).

    Each tree removal is guarded against a junction so a stray reparse point is
    detached, never recursed through (FK-43 §43.4.1.1). Files whose content is not
    the unmodified AK3-deployed content (a foreign ``.codex/config.toml`` or a
    user-modified prompt template) are preserved and reported via
    ``preserved_files`` instead of being deleted (FK-10 §10.2.9, "preserve project
    code").
    """
    removed: list[str] = []
    removed.extend(
        _remove_ak3_mcp_json(
            project_root,
            preserved_files,
            resolved_command_owners=resolved_command_owners,
        )
    )
    codex_config_removed = _remove_ak3_codex_config(
        project_root,
        preserved_files,
        resolved_command_owners=resolved_command_owners,
    )
    removed.extend(codex_config_removed)
    if codex_config_removed:
        removed.extend(_remove_empty_dir(project_root / CODEX_DIR, project_root))
    removed.extend(_safe_remove_tree(project_root / AGENTKIT_TOOLS_DIR, project_root))
    removed.extend(_safe_remove_tree(project_root / AGENTKIT_DIR, project_root))
    removed.extend(_remove_ak3_prompt_bindings(project_root, preserved_files))
    return removed


def _remove_ak3_mcp_json(
    project_root: Path,
    preserved_files: list[str],
    *,
    resolved_command_owners: Mapping[str, str],
) -> list[str]:
    """Remove only AK3 MCP values and retain foreign JSON value-equal."""
    from agentkit.backend.core_types.mcp_server_registration import (
        McpServerRegistrationError,
    )
    from agentkit.backend.utils.io import atomic_write_text

    path = project_root / ".mcp.json"
    if not path.is_file():
        return []
    try:
        raw = path.read_bytes()
        rendered = render_mcp_json_without_ak3(
            raw,
            project_root=project_root,
            resolved_command_owners=resolved_command_owners,
        )
    except (OSError, McpServerRegistrationError):
        preserved_files.append(str(path.relative_to(project_root)))
        return []
    if rendered.encode("utf-8") == raw:
        preserved_files.append(str(path.relative_to(project_root)))
        return []
    if rendered.strip() == "{}":
        return _remove_file(path, project_root)
    atomic_write_text(path, rendered)
    preserved_files.append(str(path.relative_to(project_root)))
    return []


def _remove_ak3_codex_config(
    project_root: Path,
    preserved_files: list[str],
    *,
    resolved_command_owners: Mapping[str, str],
) -> list[str]:
    """Remove ``.codex/config.toml`` ONLY when it is semantically AK3-owned.

    AG3-175 replaces the former byte comparison against a FIXED string. That
    comparison was wrong in one direction: once CP 10 merged an
    ``[mcp_servers.*]`` registration into the file, the bytes no longer matched
    the hook-only builder output, so a file AK3 had written ITSELF was classified
    foreign and left behind — and ``.codex/`` stayed non-empty so the directory
    cleanup did not fire either.

    The predicate is now ``classify_ownership`` (FK-76 §76.5.4). It is
    conservative in BOTH directions, which is what keeps the
    ``preserved_foreign_files`` guarantee from weakening:

    * AK3 hook entry, with or without AK3 MCP tables -> ``AK3_ONLY`` -> removed.
    * A foreign top-level table, a foreign MCP server, an unknown field in an AK3
      server table, or merely an added COMMENT -> ``MIXED`` -> PRESERVED. A purely
      value-based predicate could not see the comment case and would delete the
      file; the classification's final step compares bytes against the canonical
      rendering of the AK3 content found, so it can.
    * No AK3 content -> ``FOREIGN`` -> preserved.
    * Not decodable / not parsable -> ``UNREADABLE`` -> preserved. Never delete
      what cannot be read.

    ARE ownership additionally requires the real path returned by the central
    wrapper owner. A same-named foreign executable, a symlink, or unavailable
    wrapper resolution is ``MIXED`` and remains in the file. The mutation
    mechanics are unchanged: every non-``AK3_ONLY`` remainder still reports
    through ``preserved_files`` (FK-10 §10.2.9, "preserve project code").
    """
    config_path = codex_config_path(project_root)
    try:
        config_path = assert_project_local_file_path(
            project_root,
            Path(CODEX_DIR) / "config.toml",
        )
    except FilesystemContainmentError:
        if config_path.exists():
            preserved_files.append(str(config_path.relative_to(project_root)))
        return []
    if not config_path.is_file():
        return []
    try:
        raw: bytes | None = config_path.read_bytes()
    except OSError:
        raw = None
    if raw is None:
        preserved_files.append(str(config_path.relative_to(project_root)))
        return []
    hook_owner = resolved_command_owners.get(CODEX_HOOK_WRAPPER_NAME)
    hook_command = render_resolved_command(hook_owner) if hook_owner else ""
    try:
        rendered = render_without_ak3(
            raw,
            hook_command=hook_command,
            project_root=project_root,
            resolved_command_owners=resolved_command_owners,
        )
    except CodexConfigError:
        preserved_files.append(str(config_path.relative_to(project_root)))
        return []
    if rendered.encode("utf-8") == raw:
        preserved_files.append(str(config_path.relative_to(project_root)))
        return []
    if not rendered.strip():
        return _remove_file(config_path, project_root)
    from agentkit.backend.utils.io import atomic_write_text

    atomic_write_text(config_path, rendered)
    preserved_files.append(str(config_path.relative_to(project_root)))
    return []


def detach_codex_config(project_root: Path) -> tuple[str, ...]:
    """Securely remove only proven AK3 content from Codex configuration.

    This is the standalone public path used by the installer settings edge.
    It delegates to the same snapshot and surgery as :func:`detach_project`, so
    no exported callable can bypass ownership classification.
    """
    preserved_files: list[str] = []
    removed = _remove_ak3_codex_config(
        project_root,
        preserved_files,
        resolved_command_owners=_resolved_detach_command_owners(),
    )
    if removed:
        removed.extend(_remove_empty_dir(project_root / CODEX_DIR, project_root))
    return tuple(removed)


def _resolved_detach_command_owners() -> Mapping[str, str]:
    """Return one immutable snapshot of centrally resolved command owners.

    Wrapper resolution can legitimately fail after the AK3 environment was
    removed. Omitting that owner is the fail-closed result: the corresponding
    MCP table or hook stays mixed/foreign instead of inheriting deletion
    authority from an executable basename. Owners are resolved independently so
    one missing wrapper does not hide a different, still-provable AK3 binding.
    """
    owners: dict[str, str] = {}
    with suppress(OSError, RuntimeError, ValueError):
        owners[STORY_KNOWLEDGE_BASE_SERVER] = str(resolve_ak3_interpreter())
    for owner_key, wrapper_name in (
        (ARE_MCP_SERVER, ARE_MCP_WRAPPER_NAME),
        (AK3_CLAUDE_HOOK_WRAPPER, AK3_CLAUDE_HOOK_WRAPPER),
        (CODEX_HOOK_WRAPPER_NAME, CODEX_HOOK_WRAPPER_NAME),
    ):
        try:
            owners[owner_key] = str(resolve_ak3_wrapper(wrapper_name))
        except (OSError, RuntimeError, ValueError):
            continue
    return MappingProxyType(owners)


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
    if is_directory_link(path) or not path.is_dir() or any(path.iterdir()):
        return []
    path.rmdir()
    return [str(path.relative_to(project_root))]


__all__ = [
    "AK3_CLAUDE_HOOK_WRAPPER",
    "AK3_CODEX_HOOK_WRAPPER",
    "DetachResult",
    "detach_project",
]
