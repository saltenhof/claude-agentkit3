"""The official-command exemption must be the command, not a prefix of a line.

`_is_official_allow_path` returns BEFORE every danger check, so a loose match is
a guard bypass. The cases below are the ones an independent review reproduced
against the live guard -- in both directions, because a guard that blocks
correct work is the same damage as one that lets destruction through.
"""

from __future__ import annotations

import pytest

from agentkit.backend.governance.guards.branch_guard import BranchGuard


def _verdict(command: str) -> bool:
    """Return whether the guard ALLOWS ``command``."""
    decision = BranchGuard().evaluate(
        "bash_command",
        {"command": command, "operating_mode": "ai_augmented", "active_story_id": "AG3-073"},
    )
    return decision.allowed


@pytest.mark.parametrize(
    "command",
    [
        # The exemption covered the first of two commands and allowed the line.
        "agentkit reset-story && git push --force origin main",
        "agentkit reset-story & git push --force origin main",
        "agentkit reset-story ; git push --force origin main",
        "agentkit reset-story | git push --force origin main",
        # Substitution hides the second command.
        "agentkit reset-story $(git push --force origin main)",
    ],
)
def test_a_line_that_is_more_than_the_official_command_is_not_exempt(command: str) -> None:
    assert _verdict(command) is False


@pytest.mark.parametrize(
    "command",
    [
        "agentkit reset-story --story AG3-073",
        "agentkit exit-story --story AG3-073 --reason 'work finished'",
        "agentkit run-phase closure --story AG3-073",
        "agentkit split-story --story AG3-073 --into 2",
        # Quoted DATA that merely looks like syntax: the reason text is an
        # argument, not a second command.
        'agentkit exit-story --story AG3-073 --reason "docs say push --force & retry"',
        'agentkit reset-story --story AG3-073 --note "R&D branch"',
    ],
)
def test_the_official_command_with_its_own_arguments_stays_allowed(command: str) -> None:
    assert _verdict(command) is True


@pytest.mark.parametrize(
    "command",
    [
        # The prefix continues into another word -- a different command.
        "agentkit reset-story-evil --now",
        "agentkit exit-storyteller",
        # Not the official command at all.
        "git push --force origin main",
    ],
)
def test_the_exemption_itself_does_not_fire_on_a_mere_prefix(command: str) -> None:
    """Checked on the exemption, not on the verdict: the guard allows by default.

    A line that is not a dangerous git operation is allowed anyway, so an
    end-to-end ALLOW would prove nothing about the exemption.
    """
    assert BranchGuard()._is_official_allow_path(command) is False  # noqa: SLF001
