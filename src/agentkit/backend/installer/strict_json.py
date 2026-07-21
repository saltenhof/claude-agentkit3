"""Shared fail-closed JSON helpers for installer wire and config boundaries.

Pure Blutgruppe-A helpers used by:

* MCP stdio wire parsing (``mcp_conformance.protocol``)
* target-project ``.mcp.json`` loading (CP 10 / CP 10c)

Both boundaries share the same RFC 8259 / Unicode scalar rules so the
config loader cannot be more permissive than the wire loader on the
classes this module covers.

Tree walks are **iterative** (explicit stack). Recursive Python predicates
would raise ``RecursionError`` on mid-depth trees that ``json.loads`` still
accepts (~500+ levels); an iterative walk plus an explicit nesting cap
closes that class for both post-decode validation and later serialisation.
"""

from __future__ import annotations

import json
import math
from typing import Any, Final

#: Hard ceiling on JSON nesting accepted at installer wire/config boundaries.
#: Chosen well below CPython's default recursion limit so post-decode walks,
#: later ``json.dumps``, and any residual recursive consumers stay safe.
#: Trees deeper than this are rejected as nesting-limit failures, not walked
#: until the platform stack overflows.
MAX_JSON_NESTING_DEPTH: Final = 256


def reject_non_json_constant(name: str) -> object:
    """Reject Python-json extras that are not in the JSON grammar (RFC 8259).

    ``json.loads`` accepts ``NaN`` / ``Infinity`` / ``-Infinity`` by default;
    those tokens are not valid JSON.
    """
    msg = f"non-JSON constant {name!r}"
    raise json.JSONDecodeError(msg, name, 0)


def reject_duplicate_object_pairs(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    """``object_pairs_hook``: reject duplicate names on every nesting level.

    CPython's default decoder keeps the last value for duplicate keys
    (``{"id":1,"id":2}`` → ``id=2``). That is last-wins ambiguity, not a
    fail-closed interoperability boundary.
    """
    seen: set[str] = set()
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            msg = f"duplicate JSON object name {key!r}"
            raise json.JSONDecodeError(msg, key, 0)
        seen.add(key)
        out[key] = value
    return out


def exceeds_max_json_nesting(
    value: object,
    *,
    max_depth: int = MAX_JSON_NESTING_DEPTH,
) -> bool:
    """True if any path from the root exceeds ``max_depth`` (iterative).

    Depth of a leaf/scalar is 1; each object/array container adds one level.
    Uses an explicit stack so mid-depth trees never raise ``RecursionError``.
    """
    if max_depth < 1:
        return True
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > max_depth:
            return True
        if isinstance(node, dict):
            child_depth = depth + 1
            if child_depth > max_depth and node:
                return True
            for child in node.values():
                stack.append((child, child_depth))
        elif isinstance(node, list):
            child_depth = depth + 1
            if child_depth > max_depth and node:
                return True
            for child in node:
                stack.append((child, child_depth))
    return False


def contains_non_finite_float(value: object) -> bool:
    """True if ``value`` (iteratively) holds a non-finite float.

    CPython's decoder can produce ``inf`` from oversized JSON numbers such as
    ``1e400`` without emitting Infinity tokens. Walk is stack-based so deep
    but finite trees do not raise ``RecursionError``.
    """
    stack: list[object] = [value]
    while stack:
        node = stack.pop()
        if type(node) is float:
            if not math.isfinite(node):
                return True
            continue
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def contains_lone_surrogate(value: object) -> bool:
    """True if any string holds an unpaired UTF-16 surrogate code point.

    Python's ``json`` decoder accepts ``\\ud800`` (and peers) as a one-char
    string. Isolated surrogates are not Unicode scalar values; valid
    surrogate *pairs* are already composed into a single scalar by the
    decoder and must not be rejected here. Walk is stack-based.
    """
    stack: list[object] = [value]
    while stack:
        node = stack.pop()
        if type(node) is str:
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in node):
                return True
            continue
        if isinstance(node, dict):
            for key, child in node.items():
                if type(key) is str and any(
                    0xD800 <= ord(ch) <= 0xDFFF for ch in key
                ):
                    return True
                stack.append(child)
        elif isinstance(node, list):
            stack.extend(node)
    return False


__all__ = [
    "MAX_JSON_NESTING_DEPTH",
    "contains_lone_surrogate",
    "contains_non_finite_float",
    "exceeds_max_json_nesting",
    "reject_duplicate_object_pairs",
    "reject_non_json_constant",
]
