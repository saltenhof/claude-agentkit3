"""Harness-neutral PostToolUse outcome mapping helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

PostToolOutcomeDict = dict[str, object]

_EXIT_CODE_KEYS = (
    "exit_code",
    "exitCode",
    "return_code",
    "returnCode",
    "returncode",
    "status_code",
    "statusCode",
    "status",
)
_STDOUT_KEYS = ("stdout", "stdout_text", "output", "text")
_STDERR_KEYS = ("stderr", "stderr_text", "error", "message")
_EXIT_CODE_PATTERN = re.compile(
    r"(?:exit|status|return)(?: +code)? *[=:]? *(-?\d+)",
    re.IGNORECASE | re.ASCII,
)


def map_post_tool_outcome(
    tool_response: object,
    *,
    fallback_error: object = None,
) -> PostToolOutcomeDict:
    """Map a harness-native tool response to the neutral outcome dict."""

    response_fields = _mapping(tool_response)
    fallback_stderr = _string_value(fallback_error)
    fallback_stdout = tool_response if isinstance(tool_response, str) else ""
    return {
        "exit_code": _extract_exit_code(response_fields, fallback_stderr),
        "stdout": _extract_text(
            response_fields,
            _STDOUT_KEYS,
            fallback=fallback_stdout,
        ),
        "stderr": _extract_text(
            response_fields,
            _STDERR_KEYS,
            fallback=fallback_stderr,
        ),
        "tool_result": _tool_result(tool_response),
    }


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


def _extract_exit_code(
    response_fields: Mapping[str, object],
    fallback_text: str,
) -> int | None:
    for key in _EXIT_CODE_KEYS:
        parsed = _coerce_exit_code(response_fields.get(key))
        if parsed is not None:
            return parsed
    # Normalise all whitespace (including newlines) to single spaces before
    # matching so patterns like "status:\n1" are still detected.  str.split()
    # is linear and handles every whitespace variant — no regex backtracking.
    normalised = " ".join(fallback_text.split())
    match = _EXIT_CODE_PATTERN.search(normalised)
    if match is None:
        return None
    return int(match.group(1))


def _coerce_exit_code(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped.lstrip("-").isdigit():
            return int(stripped)
    return None


def _extract_text(
    response_fields: Mapping[str, object],
    keys: tuple[str, ...],
    *,
    fallback: str,
) -> str:
    for key in keys:
        if key in response_fields:
            return _string_value(response_fields[key])
    return fallback


def _string_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (Mapping, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _tool_result(value: object) -> dict[str, object] | list[object] | None:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, list):
        return value
    return None


__all__ = ["PostToolOutcomeDict", "map_post_tool_outcome"]
