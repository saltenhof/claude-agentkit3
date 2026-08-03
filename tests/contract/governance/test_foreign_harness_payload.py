"""A foreign harness may add fields; AK3 may not refuse the tool call for it.

Claude Code extends its hook payload without asking. With ``extra="forbid"``
every new field made the pre-tool hook exit 2 -- BLOCK in this interface -- so
every Bash call in every AK3-installed project was refused and no guard logic
ran at all. Measured in one session: 164 hook failures, all before the first
line of domain logic.

The existing tests could not catch it: they build minimal payloads containing
exactly the five fields the model knows, so they check AK3 against its own
assumption instead of against the harness. These two do not.
"""

from __future__ import annotations

import pytest

from agentkit.harness_client.harness_adapters.claude_code import ClaudeCodeHookEvent
from agentkit.harness_client.harness_adapters.codex.event_mapping import CodexHookEvent

#: Verbatim shape of a real Claude Code PreToolUse payload, 2026-08-03. Only
#: the first five keys are modelled; the rest arrived over time, `effort` last.
REAL_PRE_TOOL_PAYLOAD = {
    "session_id": "3aa6a7b8-45a6-4ba3-afb2-7ada4ab49e48",
    "cwd": "T:/codebase/intima",
    "tool_name": "Bash",
    "tool_input": {"command": "echo probe", "description": "probe"},
    "is_subagent": False,
    "transcript_path": "C:/Users/x/.claude/projects/p/3aa6a7b8.jsonl",
    "hook_event_name": "PreToolUse",
    "tool_use_id": "toolu_019SciKZrNPSov1vscS1s3bH",
    "permission_mode": "bypassPermissions",
    "prompt_id": "9a0bce58-9026-4efd-8858-d1e442cd3de8",
    "effort": {"level": "high"},
}


def test_the_real_payload_is_accepted() -> None:
    event = ClaudeCodeHookEvent.model_validate(REAL_PRE_TOOL_PAYLOAD)

    assert event.tool_name == "Bash"
    assert event.session_id == "3aa6a7b8-45a6-4ba3-afb2-7ada4ab49e48"


@pytest.mark.parametrize(
    "model",
    [ClaudeCodeHookEvent, CodexHookEvent],
)
def test_a_field_nobody_has_invented_yet_is_accepted(model: type) -> None:
    """The point of the rule: the NEXT unknown field must not block either.

    Pinning today's field list would pass this suite and fail on the harness's
    next release -- which is exactly how the defect reached production.
    """
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "echo probe"},
        "cwd": "T:/codebase/intima",
        "field_that_does_not_exist_yet": {"nested": ["whatever", 1, None]},
    }

    event = model.model_validate(payload)

    assert event.tool_name == "Bash"
