"""Deprecated Claude Code hook entry point.

Use ``python -m agentkit.governance.harness_adapters.claude_code`` for
new hook configurations. This module remains as a compatibility re-export
for existing callers of ``agentkit.governance.hookruntime``.
"""

from __future__ import annotations

import sys

from agentkit.governance.guard_evaluation import HookEvent, evaluate_pre_tool_use
from agentkit.governance.harness_adapters.claude_code import (
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
