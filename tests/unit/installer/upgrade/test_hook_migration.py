"""Unit tests for FK-51 §51.6 / §51.6.1 hook migration (AG3-089 AC4 / AC5).

AC4: hook migration determines changed hook definitions and calls
``Governance.register_hooks``; the git-hook dispatch migration transfers the old
dispatch.

AC5: an UNRECOGNISED pre-commit customization is saved as ``.bak`` BEFORE the
write — no silent destruction.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from agentkit.backend.governance.hook_registration import (
    HookDefinition,
    HookEventName,
    RegistrationResult,
)
from agentkit.backend.installer.upgrade.hook_migration import (
    determine_hook_definitions,
    has_dispatch_block,
    migrate_git_hook_dispatch,
    migrate_hooks,
    migrate_legacy_claude_hook_settings,
    verify_git_hook_dispatch,
)

if TYPE_CHECKING:
    from pathlib import Path


class _RecordingGovernance:
    """Records the ``register_hooks`` call (AC4 — proves the call is made).

    Minimal real-shaped governance double exposing only the ``register_hooks``
    surface the migration consumes (a live state backend is out of unit scope).
    """

    def __init__(self) -> None:
        self.calls: list[list[HookDefinition]] = []

    def register_hooks(self, hook_definitions: list[HookDefinition]) -> RegistrationResult:
        self.calls.append(hook_definitions)
        return RegistrationResult(registered=[d.matcher for d in hook_definitions], skipped=[])


def _hook(matcher: str) -> HookDefinition:
    return HookDefinition(
        hook_event_name=HookEventName.POST_TOOL_USE,
        matcher=matcher,
        command=f"agentkit-hook-claude post {matcher.lower()}",
    )


def _init_git(project_root: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )


def test_migrate_hooks_calls_register_hooks() -> None:
    """AC4: hook migration routes through ``Governance.register_hooks``."""
    governance = _RecordingGovernance()
    desired = [_hook("Bash"), _hook("Write")]

    outcome = migrate_hooks(governance, desired)  # type: ignore[arg-type]

    assert governance.calls == [desired]  # the call is proven
    assert set(outcome.registered) == {"Bash", "Write"}


def test_determine_hook_definitions_reports_obsolete_matchers() -> None:
    """AC4: removed (obsolete) hook definitions are surfaced."""
    desired = [_hook("Bash")]
    definitions, obsolete = determine_hook_definitions(desired, frozenset({"Bash", "OldMatcher"}))

    assert definitions == desired
    assert obsolete == ("OldMatcher",)


def test_migrate_hooks_reports_removed() -> None:
    """AC4: the outcome reports an obsolete matcher as removed."""
    governance = _RecordingGovernance()
    outcome = migrate_hooks(
        governance,  # type: ignore[arg-type]
        [_hook("Bash")],
        current_matchers=frozenset({"Bash", "Gone"}),
    )

    assert outcome.removed == ("Gone",)
    assert outcome.changed is True


def test_migrate_legacy_claude_hook_settings_rewrites_flat_shape(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        """
{
  "permissions": {"allow": ["Bash"]},
  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash", "command": "agentkit-hook-claude pre branch_guard"},
      {"matcher": "Bash", "command": "agentkit-hook-claude pre story_creation_guard"},
      {"matcher": "Write|Edit", "command": "/opt/foreign.sh"}
    ]
  }
}
""".strip(),
        encoding="utf-8",
    )

    changed = migrate_legacy_claude_hook_settings(tmp_path)

    assert changed is True
    import json

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["permissions"] == {"allow": ["Bash"]}
    groups = data["hooks"]["PreToolUse"]
    bash = next(group for group in groups if group["matcher"] == "Bash")
    assert [handler["command"] for handler in bash["hooks"]] == [
        "agentkit-hook-claude pre branch_guard",
        "agentkit-hook-claude pre story_creation_guard",
    ]
    assert all("command" not in group for group in groups)

    second = migrate_legacy_claude_hook_settings(tmp_path)

    assert second is False


def test_migrate_legacy_claude_hook_settings_preserves_three_level_shape(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    content = """
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {"type": "command", "command": "agentkit-hook-claude pre branch_guard"}
        ]
      }
    ]
  }
}
""".strip()
    settings_path.write_text(content, encoding="utf-8")

    changed = migrate_legacy_claude_hook_settings(tmp_path)

    assert changed is False
    assert settings_path.read_text(encoding="utf-8") == content


def test_git_hook_dispatch_migration_no_hook(tmp_path: Path) -> None:
    """AC4: absent hooks are materialized so both dispatch rings really fire."""
    _init_git(tmp_path)
    outcome = migrate_git_hook_dispatch(tmp_path)

    assert outcome.migrated is True
    assert outcome.backup_path is None
    verify_git_hook_dispatch(tmp_path)


def test_git_hook_dispatch_migration_replaces_recognised_secret_owner(
    tmp_path: Path,
) -> None:
    """AC4: the legacy secret owner is removed instead of duplicated."""
    _init_git(tmp_path)
    hook = tmp_path / "tools" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text(
        "#!/bin/sh\n"
        "# agentkit secret-detection (global)\n"
        "python -m agentkit.backend.governance.guard_system.secret_scan --staged\n",
        encoding="utf-8",
    )

    outcome = migrate_git_hook_dispatch(tmp_path)

    assert outcome.migrated is True
    assert outcome.backup_path is None
    content = hook.read_text(encoding="utf-8")
    assert has_dispatch_block(content)
    assert "agentkit secret-detection" not in content
    assert "guard_system.secret_scan" not in content
    assert not hook.with_name("pre-commit.bak").exists()


def test_git_hook_dispatch_migration_unrecognised_hook_writes_bak(
    tmp_path: Path,
) -> None:
    """AC5: an unrecognised pre-hook remains active through the chain owner."""
    _init_git(tmp_path)
    hook = tmp_path / "tools" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    old_content = "#!/bin/sh\n# hand-rolled custom hook\necho mine\n"
    hook.write_text(old_content, encoding="utf-8")

    outcome = migrate_git_hook_dispatch(tmp_path)

    assert outcome.migrated is True
    assert outcome.backup_path is not None
    backup = hook.with_name("pre-commit.bak")
    # AC5: the old (unrecognised) hook content is preserved byte-for-byte.
    assert backup.read_text(encoding="utf-8") == old_content
    # The migrated hook now carries the dispatch block.
    assert has_dispatch_block(hook.read_text(encoding="utf-8"))


def test_git_hook_dispatch_migration_idempotent(tmp_path: Path) -> None:
    """A fully materialized pre/post pair is a no-op on the second call."""
    _init_git(tmp_path)
    first = migrate_git_hook_dispatch(tmp_path)
    assert first.migrated is True

    outcome = migrate_git_hook_dispatch(tmp_path)

    assert outcome.migrated is False
    assert outcome.backup_path is None
    verify_git_hook_dispatch(tmp_path)
