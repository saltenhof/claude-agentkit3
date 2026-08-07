"""Hook + git-hook dispatching migration on upgrade (FK-51 §51.6 / §51.6.1).

Two migration paths:

* :func:`migrate_hooks` (§51.6) — determine the changed/new/removed hook
  definitions for the current version and re-materialise them through the
  hook-registration surface ``register_hooks`` (story AC4). Hooks are
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
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.installer.git_hook_dispatch import (
    GIT_HOOK_DISPATCH_MARKERS,
    POST_COMMIT_DISPATCH_MARKERS,
    GitHookMigrationOutcome,
    has_dispatch_block,
    migrate_git_hook_dispatch,
    verify_git_hook_dispatch,
)
from agentkit.harness_client.harness_adapters.settings_writer import (
    normalize_claude_hooks_section,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.governance.hook_registration import HookDefinition, RegistrationResult


class HookRegistrationSurface(Protocol):
    """Narrow UP04 dependency implemented by Governance and writer adapters."""

    def register_hooks(
        self,
        hook_definitions: list[HookDefinition],
    ) -> RegistrationResult:
        """Persist and materialize the supplied hook definitions."""
        ...


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
    governance: HookRegistrationSurface,
    desired: list[HookDefinition],
    *,
    current_matchers: frozenset[str] = frozenset(),
) -> HookMigrationOutcome:
    """Migrate project hooks via ``Governance.register_hooks`` (FK-51 §51.6, AC4).

    Determines the changed/new/removed hook definitions and re-materialises them
    through the injected hook-registration surface — never a
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
            "Existing .claude/settings.json must be a JSON object (fail-closed).",
        )
    if "hooks" not in settings:
        return False
    normalized = normalize_claude_hooks_section(settings.get("hooks"))
    if not normalized.changed:
        return False
    settings["hooks"] = normalized.hooks_section
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return True


__all__ = [
    "GIT_HOOK_DISPATCH_MARKERS",
    "POST_COMMIT_DISPATCH_MARKERS",
    "GitHookMigrationOutcome",
    "HookMigrationOutcome",
    "determine_hook_definitions",
    "has_dispatch_block",
    "migrate_legacy_claude_hook_settings",
    "migrate_git_hook_dispatch",
    "migrate_hooks",
    "verify_git_hook_dispatch",
]
