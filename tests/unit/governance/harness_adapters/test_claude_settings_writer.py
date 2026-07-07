"""Unit tests for Claude Code settings writer shape and merge semantics."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.backend.governance.hook_registration import HookDefinition, HookEventName
from agentkit.harness_client.harness_adapters.settings_writer import (
    ClaudeCodeSettingsWriter,
)

if TYPE_CHECKING:
    from pathlib import Path


def _hook(command: str, matcher: str = "Bash") -> HookDefinition:
    return HookDefinition(
        hook_event_name=HookEventName.PRE_TOOL_USE,
        matcher=matcher,
        command=command,
    )


def test_shared_matcher_commands_become_handlers_in_one_group(tmp_path: Path) -> None:
    writer = ClaudeCodeSettingsWriter(tmp_path)

    writer.write(
        [
            _hook("agentkit-hook-claude pre branch_guard"),
            _hook("agentkit-hook-claude pre story_creation_guard"),
            _hook("agentkit-hook-claude pre branch_guard"),
        ]
    )

    data = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    groups = data["hooks"]["PreToolUse"]
    assert len([g for g in groups if g["matcher"] == "Bash"]) == 1
    bash = groups[0]
    assert "command" not in bash
    assert [handler["command"] for handler in bash["hooks"]] == [
        "agentkit-hook-claude pre branch_guard",
        "agentkit-hook-claude pre story_creation_guard",
    ]


def test_existing_foreign_group_and_handler_survive_merge(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash"]},
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {"type": "command", "command": "/opt/foreign.sh"}
                            ],
                            "note": "foreign",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    ClaudeCodeSettingsWriter(tmp_path).write(
        [_hook("agentkit-hook-claude pre branch_guard")]
    )

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    group = data["hooks"]["PreToolUse"][0]
    assert group["note"] == "foreign"
    assert data["permissions"] == {"allow": ["Bash"]}
    assert [handler["command"] for handler in group["hooks"]] == [
        "/opt/foreign.sh",
        "agentkit-hook-claude pre branch_guard",
    ]


def test_legacy_flat_entries_are_normalized_without_losing_foreign(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "theme": "dark",
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "command": "/opt/foreign.sh",
                            "args": ["--audit"],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    ClaudeCodeSettingsWriter(tmp_path).write(
        [_hook("agentkit-hook-claude pre branch_guard")]
    )

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    group = data["hooks"]["PreToolUse"][0]
    assert data["theme"] == "dark"
    assert group["matcher"] == "Bash"
    assert group["hooks"] == [
        {"command": "/opt/foreign.sh", "args": ["--audit"], "type": "command"},
        {"type": "command", "command": "agentkit-hook-claude pre branch_guard"},
    ]
