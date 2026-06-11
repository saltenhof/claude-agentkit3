"""Unit tests for FK-51 §51.6 / §51.6.1 hook migration (AG3-089 AC4 / AC5).

AC4: hook migration determines changed hook definitions and calls
``Governance.register_hooks``; the git-hook dispatch migration transfers the old
dispatch.

AC5: an UNRECOGNISED pre-commit customization is saved as ``.bak`` BEFORE the
write — no silent destruction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.governance.hook_registration import (
    HookDefinition,
    HookEventName,
    RegistrationResult,
)
from agentkit.installer.upgrade.config_migration import BACKUP_SUFFIX
from agentkit.installer.upgrade.hook_migration import (
    GIT_HOOK_DISPATCH_MARKERS,
    determine_hook_definitions,
    has_dispatch_block,
    migrate_git_hook_dispatch,
    migrate_hooks,
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

    def register_hooks(
        self, hook_definitions: list[HookDefinition]
    ) -> RegistrationResult:
        self.calls.append(hook_definitions)
        return RegistrationResult(
            registered=[d.matcher for d in hook_definitions], skipped=[]
        )


def _hook(matcher: str) -> HookDefinition:
    return HookDefinition(
        hook_event_name=HookEventName.POST_TOOL_USE,
        matcher=matcher,
        command=f"agentkit-hook-claude post {matcher.lower()}",
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
    definitions, obsolete = determine_hook_definitions(
        desired, frozenset({"Bash", "OldMatcher"})
    )

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


def test_git_hook_dispatch_migration_no_hook(tmp_path: Path) -> None:
    """No pre-commit present -> nothing to migrate."""
    outcome = migrate_git_hook_dispatch(tmp_path)

    assert outcome.migrated is False
    assert outcome.backup_path is None


def test_git_hook_dispatch_migration_recognised_hook_appends_block(
    tmp_path: Path,
) -> None:
    """AC4: a recognised AgentKit pre-commit gets the dispatch block appended."""
    hook = tmp_path / "tools" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text(
        "#!/bin/sh\n# agentkit secret-detection (global)\n", encoding="utf-8"
    )

    outcome = migrate_git_hook_dispatch(tmp_path)

    assert outcome.migrated is True
    assert outcome.backup_path is None  # recognised -> no `.bak`
    content = hook.read_text(encoding="utf-8")
    assert has_dispatch_block(content)
    assert "agentkit secret-detection" in content  # secret-detection preserved


def test_git_hook_dispatch_migration_unrecognised_hook_writes_bak(
    tmp_path: Path,
) -> None:
    """AC5: an UNRECOGNISED pre-commit customization is preserved as ``.bak``."""
    hook = tmp_path / "tools" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    old_content = "#!/bin/sh\n# hand-rolled custom hook\necho mine\n"
    hook.write_text(old_content, encoding="utf-8")

    outcome = migrate_git_hook_dispatch(tmp_path)

    assert outcome.migrated is True
    assert outcome.backup_path is not None
    backup = hook.with_name("pre-commit" + BACKUP_SUFFIX)
    # AC5: the old (unrecognised) hook content is preserved byte-for-byte.
    assert backup.read_text(encoding="utf-8") == old_content
    # The migrated hook now carries the dispatch block.
    assert has_dispatch_block(hook.read_text(encoding="utf-8"))


def test_git_hook_dispatch_migration_idempotent(tmp_path: Path) -> None:
    """A hook already carrying the dispatch block is a no-op (idempotent)."""
    hook = tmp_path / "tools" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text(
        f"#!/bin/sh\n{GIT_HOOK_DISPATCH_MARKERS[0]}\nx\n{GIT_HOOK_DISPATCH_MARKERS[1]}\n",
        encoding="utf-8",
    )

    outcome = migrate_git_hook_dispatch(tmp_path)

    assert outcome.migrated is False
    assert outcome.backup_path is None
