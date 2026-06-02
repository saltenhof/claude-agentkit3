"""CLI entry point for Codex pre-tool governance hooks.

Official CLI entry point for Codex hooks:
``agentkit-hook-codex {phase} {hook_id}``

Invalid arguments (unknown phase or hook_id) return exit code 2 with a
message on stderr.  Allowed decisions return exit code 0; blocked
decisions return exit code 2.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from agentkit.governance.harness_adapters.codex.decision_mapping import (
    CodexHookOutput,
    codex_exit_code,
    to_codex_output,
)
from agentkit.governance.harness_adapters.codex.event_mapping import (
    CodexHookEvent,
    to_neutral_event,
)
from agentkit.governance.runner import Governance, parse_hook_wrapper_args


def main(argv: list[str] | None = None) -> int:
    """Parse args, read stdin, evaluate governance hook, return exit code.

    Args:
        argv: Command-line arguments after the script name.  When ``None``,
            ``sys.argv[1:]`` is used.  Expected format:
            ``{phase} {hook_id}`` (e.g. ``pre branch_guard``).

    Returns:
        0 on ALLOW, 2 on BLOCK or invalid arguments.
    """
    args = list(sys.argv[1:]) if argv is None else list(argv)
    try:
        selector = parse_hook_wrapper_args(args, command_name="agentkit-hook-codex")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        codex_event = _parse_hook_event(sys.stdin.read())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    neutral_event = to_neutral_event(codex_event)
    try:
        verdict = Governance.run_hook(
            selector.hook_id,
            neutral_event,
            phase=selector.phase,
            project_root=Path.cwd(),
        )
        output = to_codex_output(verdict)
    except Exception as exc:  # noqa: BLE001 — outermost fail-closed safety net.
        # AG3-032 ERROR 6 / FK-55 §55.10.5 / FK-31 §31.2.7: a governance hook
        # must NEVER let an evaluation fault escape and silently allow the tool
        # call. Any escaping exception is mapped to a fail-closed BLOCK (exit 2).
        output = CodexHookOutput(
            decision="block",
            guard="principal_capability",
            message=f"governance hook failed fail-closed: {exc}",
            detail={"fault_class": type(exc).__name__},
        )
    print(json.dumps(output.model_dump(exclude_none=True), sort_keys=True))
    return codex_exit_code(output)


def _parse_hook_event(raw: str) -> CodexHookEvent:
    try:
        return CodexHookEvent.model_validate_json(raw)
    except ValidationError as exc:
        message = str(exc)
        if "tool_input" in message:
            raise RuntimeError("tool_input must be a JSON object") from exc
        if "Input should be an object" in message:
            raise RuntimeError("Hook payload must be a JSON object") from exc
        raise RuntimeError(str(exc)) from exc


__all__ = [
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
