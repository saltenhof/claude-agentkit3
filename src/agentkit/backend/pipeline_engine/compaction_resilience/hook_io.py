"""Shared hook input/output helpers for FK-36 modules."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from agentkit.backend.pipeline_engine.compaction_resilience.models import coerce_json_object


def read_hook_input() -> dict[str, Any]:
    """Read a JSON object from stdin, returning an empty object on blank input."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return coerce_json_object(json.loads(raw))
    except json.JSONDecodeError:
        warn("invalid hook JSON input; fail-open")
        return {}


def hook_cwd(data: dict[str, Any]) -> Path:
    """Return hook cwd from input, falling back to process cwd."""
    cwd = data.get("cwd")
    if isinstance(cwd, str) and cwd:
        return Path(cwd)
    return Path.cwd()


def warn(message: str) -> None:
    """Write a FK-36 warning to stderr."""
    print(f"[compaction-resilience warning] {message}", file=sys.stderr)


def emit_additional_context(context: str) -> None:
    """Emit Claude Code PreToolUse additionalContext JSON."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": context,
                }
            },
            sort_keys=True,
        )
    )


def load_json_file(path: Path) -> dict[str, Any] | None:
    """Load a JSON object from ``path``; return ``None`` for invalid content."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warn(f"cannot read JSON artifact {path}: {exc}; fail-open")
        return None
    return coerce_json_object(payload)


__all__ = [
    "emit_additional_context",
    "hook_cwd",
    "load_json_file",
    "read_hook_input",
    "warn",
]
