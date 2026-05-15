"""CCAG Gate-Keeper Hook CLI entry point.

This module provides the ``python -m agentkit.governance.ccag`` CLI entry
point for the CCAG gate-keeper hook.  In production it is invoked by the
``agentkit-hook-claude pre ccag_gatekeeper`` wrapper (the canonical path
recommended by FK-42 §42.5.2 / F-42-030) which goes through the harness
adapter and the Governance dispatcher.

This standalone entry point exists as a convenience for:
- Direct invocation during development/debugging.
- Harness environments that cannot use the multi-step wrapper.

**Recommended invocation (via harness adapter):**

    agentkit-hook-claude pre ccag_gatekeeper

This goes through:
    ``agentkit.governance.harness_adapters.claude_code:main``
    → ``Governance.run_hook(phase="pre", hook_id="ccag_gatekeeper", event=...)``
    → ``CcagPermissionRuntime.evaluate(event)``

**Standalone invocation:**

    python -m agentkit.governance.ccag

Reads a PreToolUse JSON event from stdin, evaluates CCAG rules, and
exits with 0 (allow) or 2 (block).

Exit code contract (FK-42 / F-42-017 / F-42-018):
    Exit 0 — allow or unknown_permission (host dialog handles it).
    Exit 2 — block_by_rule (opaque message printed to stderr).

Hook chain position (FK-42 §42.5.2 / F-42-030):
    CCAG is the LAST PreToolUse hook.  Hard guards run first and have
    absolute priority.  CCAG only sees calls that passed all guards.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from agentkit.projectedge.runtime import FreshnessClass


class _CcagHookInput(BaseModel):
    """Pydantic model for the stdin JSON payload of the CCAG standalone CLI.

    Claude Code sends a PreToolUse JSON blob with at least ``tool_name``
    and ``tool_input``.  All fields are optional to tolerate partial
    invocations from harness environments.
    """

    tool_name: str = ""
    tool_input: dict[str, Any] = {}
    is_subagent: bool = False
    cwd: str = ""
    session_id: str | None = None
    operating_mode: str = ""


def main() -> None:
    """CCAG standalone PreToolUse hook entry point.

    Reads JSON from stdin, evaluates CCAG rules via
    :class:`~agentkit.governance.ccag.runtime.CcagPermissionRuntime`,
    exits 0 on allow/unknown or 2 on block.

    This function intentionally imports lazily to keep start-up overhead
    minimal — it is called on every hook invocation.
    """
    from agentkit.governance.ccag.rules import OPAQUE_MESSAGE
    from agentkit.governance.ccag.runtime import CcagDecisionKind, CcagPermissionRuntime
    from agentkit.governance.guard_evaluation import HookEvent, Operation

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        data = _CcagHookInput.model_validate_json(raw)
        tool_name = data.tool_name
        tool_input: dict[str, object] = dict(data.tool_input)
        is_subagent = data.is_subagent
        cwd = data.cwd

        # Resolve rules directory from cwd or default
        rules_dir: Path | None = None
        if cwd:
            rules_dir = Path(cwd) / ".agentkit" / "ccag" / "rules"

        # Build harness-neutral event
        # Map raw tool_name to operation — conservative mapping
        _tool_to_op: dict[str, Operation] = {
            "Bash": "bash_command",
            "Write": "file_write",
            "Edit": "file_edit",
            "Read": "file_read",
            "Glob": "file_read",
            "Grep": "file_read",
        }
        operation: Operation = _tool_to_op.get(tool_name, "unknown_tool")
        freshness: FreshnessClass = (
            "baseline_read"
            if operation == "file_read"
            else "mutation"
            if operation in ("bash_command", "file_write", "file_edit")
            else "guarded_read"
        )
        # Inject tool_name into args so runtime can recover it
        args: dict[str, object] = {
            "tool_name": tool_name,
            **tool_input,
        }
        # Inject operating_mode if provided (for story_execution mode detection)
        if data.operating_mode:
            args["operating_mode"] = data.operating_mode

        event = HookEvent(
            operation=operation,
            operation_args=args,
            freshness_class=freshness,
            cwd=cwd or str(Path.cwd()),
            session_id=data.session_id,
            principal_kind="subagent" if is_subagent else "main",
        )

        runtime = CcagPermissionRuntime(rules_dir=rules_dir)
        decision = runtime.evaluate(event)

        if decision.kind == CcagDecisionKind.BLOCK_BY_RULE:
            print(OPAQUE_MESSAGE, file=sys.stderr)
            sys.exit(2)

        # allow or unknown_permission → exit 0 (host dialog handles unknown)
        sys.exit(0)

    except Exception:  # noqa: BLE001
        # Fail-open: unexpected errors must not block legitimate operations.
        # CCAG is a comfort layer; hard Guards are the last line of defence.
        sys.exit(0)


if __name__ == "__main__":
    main()
