"""Detach may only remove hooks AK3 actually owns (FK-10 §10.2.9).

Detach DELETES what it matches, so a wrong match destroys a foreign project's
own configuration. Ownership was asserted by substring: any command line
mentioning an AK3 name counted as ours. These cases are the counter-examples
that were removed in the field.
"""

from __future__ import annotations

import pytest

from agentkit.backend.installer.lifecycle.detach import _is_ak3_hook_command


@pytest.mark.parametrize(
    "command",
    [
        # Foreign hooks that merely MENTION an AK3 name.
        'echo "agentkit-hook-codex" && ./foreign-quality-gate',
        "echo agentkit-hook-claude; ./foreign-gate",
        "./foreign-gate || agentkit-hook-claude",
        # Foreign paths that merely CONTAIN the AK3 directory names.
        "sh /opt/.agentkit/hooks-backup/quality.sh",
        "python /opt/.agentkit/cache/hooks/foreign.sh",
        "python hooks/.agentkit/foreign.py",
        # The AK3 path is MENTIONED, not executed.
        "echo .agentkit/hooks/story_guard.py",
        "foreign-tool --config /srv/.agentkit/hooks/config",
        "cat .agentkit/hooks/story_guard.py",
        # Not a command at all.
        "",
    ],
)
def test_foreign_hook_commands_are_not_claimed(command: str) -> None:
    assert _is_ak3_hook_command(command) is False


@pytest.mark.parametrize(
    "command",
    [
        "agentkit-hook-claude pre branch_guard",
        "agentkit-hook-codex post commit",
        "python .agentkit/hooks/story_guard.py",
        "python /srv/project/.agentkit/hooks/story_guard.py",
    ],
)
def test_ak3_owned_hook_commands_are_claimed(command: str) -> None:
    assert _is_ak3_hook_command(command) is True


def test_unparsable_shell_is_left_alone() -> None:
    """What cannot be parsed cannot be proven ours -- so it stays."""
    assert _is_ak3_hook_command('agentkit-hook-claude "unterminated') is False
