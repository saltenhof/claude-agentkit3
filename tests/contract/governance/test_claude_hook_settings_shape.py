"""Contract: Claude Code hook settings use the real three-level shape."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.governance.hook_registration import HookDefinition, HookEventName
from agentkit.harness_client.harness_adapters.settings_writer import (
    ClaudeCodeSettingsWriter,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.contract
def test_claude_settings_shape_is_event_group_handlers(tmp_path: Path) -> None:
    writer = ClaudeCodeSettingsWriter(tmp_path)

    writer.write(
        [
            HookDefinition(
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="agentkit-hook-claude pre branch_guard",
            ),
            HookDefinition(
                hook_event_name=HookEventName.PRE_TOOL_USE,
                matcher="Bash",
                command="agentkit-hook-claude pre story_creation_guard",
            ),
        ]
    )

    data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    groups = data["hooks"]["PreToolUse"]
    assert groups == [
        {
            "matcher": "Bash",
            "hooks": [
                {
                    "type": "command",
                    "command": "agentkit-hook-claude pre branch_guard",
                },
                {
                    "type": "command",
                    "command": "agentkit-hook-claude pre story_creation_guard",
                },
            ],
        }
    ]
    assert "command" not in groups[0]
