"""Hook + git-hook dispatching migration on upgrade (FK-51 §51.6 / §51.6.1).

Two migration paths:

* :func:`migrate_hooks` (§51.6) — determine the changed/new/removed hook
  definitions for the current version and re-materialise them through the
  governance top surface ``Governance.register_hooks`` (story AC4). Hooks are
  NEVER written directly; the owner BC (``governance-and-guards``) materialises
  the harness settings.
* :func:`migrate_git_hook_dispatch` (§51.6.1) — migrate a pre-dispatching
  ``tools/hooks/pre-commit`` to the path-based dispatching logic (secret-detection
  global, version-bump on code changes, concept-validation on concept changes).
  An UNRECOGNISED pre-commit customization is saved as ``.bak`` BEFORE the write —
  never silently destroyed (story AC5, F-51-023 spirit for the git-hook path).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from agentkit.backend.installer.upgrade.config_migration import BACKUP_SUFFIX, backup_config_file
from agentkit.harness_client.harness_adapters.settings_writer import (
    normalize_claude_hooks_section,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.governance.hook_registration import HookDefinition, RegistrationResult
    from agentkit.backend.governance.runner import Governance

#: Marker lines that identify the AgentKit-managed dispatching block of a
#: ``pre-commit`` hook (FK-51 §51.6.1). Their presence means the dispatching
#: migration already ran (idempotency) and the surrounding content is recognised.
GIT_HOOK_DISPATCH_MARKERS: Final[tuple[str, ...]] = (
    "# >>> agentkit pre-commit dispatch >>>",
    "# <<< agentkit pre-commit dispatch <<<",
)

#: A line every AgentKit-installed pre-commit carries (secret-detection is global,
#: FK-51 §51.6.1 step 1). Its presence is how the migration recognises an
#: AgentKit-origin hook vs a foreign one.
_SECRET_DETECTION_MARKER: Final = "agentkit secret-detection"

#: The dispatching block appended by the migration (FK-51 §51.6.1 steps 2-3).
_DISPATCH_BLOCK: Final = (
    f"{GIT_HOOK_DISPATCH_MARKERS[0]}\n"
    "# Path-based dispatching (FK-51 §51.6.1):\n"
    "#  - secret-detection: global (always active)\n"
    "#  - version-bump: only on code changes (agentkit/, pyproject.toml)\n"
    "#  - concept-validation: only on concept changes (concept/)\n"
    'changed=$(git diff --cached --name-only)\n'
    'case "$changed" in\n'
    "  *concept/*) python -m agentkit.concept_validate --staged ;;\n"
    "esac\n"
    f"{GIT_HOOK_DISPATCH_MARKERS[1]}\n"
)


@dataclass(frozen=True)
class HookMigrationOutcome:
    """Result of the §51.6 hook migration.

    Attributes:
        registered: Matcher strings the migration (re-)registered.
        skipped: Matcher strings already current (idempotent).
        removed: Matcher strings of obsolete hook definitions removed.
        changed: Whether the registration produced any change.
    """

    registered: tuple[str, ...] = field(default_factory=tuple)
    skipped: tuple[str, ...] = field(default_factory=tuple)
    removed: tuple[str, ...] = field(default_factory=tuple)

    @property
    def changed(self) -> bool:
        """Return whether the migration registered or removed anything."""
        return bool(self.registered) or bool(self.removed)


@dataclass(frozen=True)
class GitHookMigrationOutcome:
    """Result of the §51.6.1 git-hook dispatching migration.

    Attributes:
        migrated: Whether the dispatching block was added in this run.
        backup_path: The ``.bak`` path written for an unrecognised customization
            (``None`` when nothing unrecognised had to be preserved).
        detail: Human-readable description.
    """

    migrated: bool
    backup_path: Path | None
    detail: str


def determine_hook_definitions(
    desired: list[HookDefinition],
    current_matchers: frozenset[str],
) -> tuple[list[HookDefinition], tuple[str, ...]]:
    """Split desired hooks into (to-register, obsolete-matchers) (FK-51 §51.6).

    The migration registers the desired (current-version) hook definitions and
    reports which previously-registered matchers are now obsolete (present in
    ``current_matchers`` but not in ``desired``) — the new/changed/removed split
    of FK-51 §51.6. ``Governance.register_hooks`` is idempotent for unchanged
    entries, so re-registering the full desired set is the canonical path.

    Args:
        desired: The desired hook definitions for the current version.
        current_matchers: Matchers currently registered for the project.

    Returns:
        A ``(definitions_to_register, obsolete_matchers)`` pair.
    """
    desired_matchers = {definition.matcher for definition in desired}
    obsolete = tuple(sorted(current_matchers - desired_matchers))
    return desired, obsolete


def migrate_hooks(
    governance: Governance,
    desired: list[HookDefinition],
    *,
    current_matchers: frozenset[str] = frozenset(),
) -> HookMigrationOutcome:
    """Migrate project hooks via ``Governance.register_hooks`` (FK-51 §51.6, AC4).

    Determines the changed/new/removed hook definitions and re-materialises them
    through the governance top surface ``Governance.register_hooks`` — never a
    direct settings write (story §5 FIX-THE-MODEL). The obsolete matchers are
    surfaced in the outcome (their removal is the owner BC's responsibility on the
    next registration; the migration reports them so a caller can act).

    Args:
        governance: The governance top surface to register through.
        desired: The desired hook definitions for the current version.
        current_matchers: Matchers currently registered (for the obsolete split).

    Returns:
        The :class:`HookMigrationOutcome` mirroring the ``RegistrationResult``.
    """
    definitions, obsolete = determine_hook_definitions(desired, current_matchers)
    result: RegistrationResult = governance.register_hooks(definitions)
    return HookMigrationOutcome(
        registered=tuple(result.registered),
        skipped=tuple(result.skipped),
        removed=obsolete,
    )


def migrate_legacy_claude_hook_settings(project_root: Path) -> bool:
    """Rewrite persisted flat Claude hook settings to the canonical shape.

    Existing AG3 installs before AG3-147 may carry flat Claude entries like
    ``{"matcher": "Bash", "command": "agentkit-hook-claude pre branch_guard"}``.
    The harness writer owns the single normalization rule; upgrade invokes it
    here to preserve foreign settings while emitting only the real Claude Code
    three-level shape on disk.

    Args:
        project_root: The target-project root.

    Returns:
        ``True`` when the settings file was rewritten, otherwise ``False``.

    Raises:
        ValueError: If a present settings file or ``hooks`` section is malformed.
        OSError: If the settings file cannot be read or written.
    """
    settings_path = project_root / ".claude" / "settings.json"
    if not settings_path.is_file():
        return False
    import json

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise ValueError(
            "Existing .claude/settings.json must be a JSON object "
            "(fail-closed).",
        )
    if "hooks" not in settings:
        return False
    normalized = normalize_claude_hooks_section(settings.get("hooks"))
    if not normalized.changed:
        return False
    settings["hooks"] = normalized.hooks_section
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return True


def _pre_commit_path(project_root: Path) -> Path:
    """Return the target-project ``tools/hooks/pre-commit`` path (FK-51 §51.6.1)."""
    return project_root / "tools" / "hooks" / "pre-commit"


def has_dispatch_block(content: str) -> bool:
    """Return whether ``content`` already carries the AgentKit dispatch block."""
    return all(marker in content for marker in GIT_HOOK_DISPATCH_MARKERS)


def _is_recognised_pre_commit(content: str) -> bool:
    """Return whether a pre-commit is AgentKit-origin (recognised) (§51.6.1).

    A pre-commit is recognised when it carries the AgentKit secret-detection
    marker (every AgentKit-installed pre-commit does, FK-51 §51.6.1 step 1) or it
    already has the dispatch block. Anything else is an UNRECOGNISED customization
    whose content must be preserved as ``.bak`` before the migration writes.
    """
    return _SECRET_DETECTION_MARKER in content or has_dispatch_block(content)


def migrate_git_hook_dispatch(project_root: Path) -> GitHookMigrationOutcome:
    """Migrate the pre-commit hook to path-based dispatching (FK-51 §51.6.1, AC5).

    Steps (FK-51 §51.6.1):

    1. If no ``tools/hooks/pre-commit`` exists -> nothing to migrate.
    2. If the dispatch block is already present -> idempotent no-op.
    3. If the existing hook is RECOGNISED (AgentKit secret-detection origin) ->
       append the dispatch block in place (secret-detection stays unchanged).
    4. If the existing hook is UNRECOGNISED (a foreign/hand-edited pre-commit) ->
       save its content as ``<pre-commit>.bak`` FIRST (never silently destroyed),
       then write the recognised hook with the dispatch block. The ``.bak`` makes
       the human's customization recoverable (story AC5).

    Args:
        project_root: The target-project root.

    Returns:
        The :class:`GitHookMigrationOutcome`.
    """
    hook_path = _pre_commit_path(project_root)
    if not hook_path.is_file():
        return GitHookMigrationOutcome(
            migrated=False,
            backup_path=None,
            detail="No tools/hooks/pre-commit present; nothing to migrate.",
        )
    content = hook_path.read_text(encoding="utf-8")
    if has_dispatch_block(content):
        return GitHookMigrationOutcome(
            migrated=False,
            backup_path=None,
            detail="pre-commit already carries the dispatch block (idempotent).",
        )

    from agentkit.backend.utils.io import atomic_write_text

    if _is_recognised_pre_commit(content):
        # Recognised AgentKit hook: append the dispatch block, secret-detection
        # untouched (FK-51 §51.6.1 step 2 — secret-detection stays unchanged).
        new_content = content
        if not new_content.endswith("\n"):
            new_content += "\n"
        new_content += _DISPATCH_BLOCK
        atomic_write_text(hook_path, new_content)
        return GitHookMigrationOutcome(
            migrated=True,
            backup_path=None,
            detail="Appended dispatch block to recognised AgentKit pre-commit.",
        )

    # UNRECOGNISED customization: preserve it as `.bak` BEFORE writing (story AC5,
    # F-51-023 spirit — no silent destruction). ``backup_config_file`` writes an
    # atomic, byte-identical `.bak`.
    backup_path = backup_config_file(hook_path)
    migrated_hook = (
        "#!/bin/sh\n"
        f"# {_SECRET_DETECTION_MARKER} (global, FK-51 §51.6.1 step 1)\n"
        "python -m agentkit.secret_detection --staged\n"
        f"{_DISPATCH_BLOCK}"
    )
    atomic_write_text(hook_path, migrated_hook)
    return GitHookMigrationOutcome(
        migrated=True,
        backup_path=backup_path,
        detail=(
            "Unrecognised pre-commit customization preserved as "
            f"{backup_path.name} ({BACKUP_SUFFIX}); migrated hook written."
        ),
    )


__all__ = [
    "GIT_HOOK_DISPATCH_MARKERS",
    "GitHookMigrationOutcome",
    "HookMigrationOutcome",
    "determine_hook_definitions",
    "has_dispatch_block",
    "migrate_legacy_claude_hook_settings",
    "migrate_git_hook_dispatch",
    "migrate_hooks",
]
