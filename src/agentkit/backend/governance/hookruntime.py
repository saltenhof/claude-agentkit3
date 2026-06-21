"""Deprecated Claude Code hook entry point.

Use ``python -m agentkit.harness_client.harness_adapters.claude_code`` for
new hook configurations. This module remains as a compatibility re-export
for existing callers of ``agentkit.backend.governance.hookruntime``.
"""

from __future__ import annotations

import sys

from agentkit.backend.governance.guard_evaluation import HookEvent, evaluate_pre_tool_use
from agentkit.harness_client.harness_adapters.claude_code import (
    ClaudeCodeHookEvent,
    main,
    to_neutral_event,
)

__all__ = [
    "ClaudeCodeHookEvent",
    "HookEvent",
    "evaluate_pre_tool_use",
    "main",
    "to_neutral_event",
]


if __name__ == "__main__":
    sys.exit(main())
