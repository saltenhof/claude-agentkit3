"""CLI entry point for Codex pre-tool governance hooks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from agentkit.governance.guard_evaluation import evaluate_pre_tool_use
from agentkit.governance.harness_adapters.codex.decision_mapping import (
    codex_exit_code,
    to_codex_output,
)
from agentkit.governance.harness_adapters.codex.event_mapping import (
    CodexHookEvent,
    to_neutral_event,
)


def main(argv: list[str] | None = None) -> int:
    """Read one Codex hook event from stdin and return the hook exit code."""
    del argv
    codex_event = _parse_hook_event(sys.stdin.read())
    neutral_event = to_neutral_event(codex_event)
    verdict = evaluate_pre_tool_use(neutral_event, project_root=Path.cwd())
    output = to_codex_output(verdict)
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
