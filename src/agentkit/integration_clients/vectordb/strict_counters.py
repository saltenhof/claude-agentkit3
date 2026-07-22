"""Strict external-response counter parsing (AG3-174 R07).

Accepts ONLY a complete structured shape with exact non-bool integers for
``matches``, ``successful`` and ``failed``. No mapping defaults, no bare-int
legacy path, no ``isinstance(True, int)`` leak.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from agentkit.integration_clients.vectordb.errors import VectorDbWriteError

_REQUIRED_KEYS: Final[tuple[str, ...]] = ("matches", "successful", "failed")


def require_strict_int(value: object, *, field: str) -> int:
    """Require a real int (bool/float/str rejected — no ``int()`` coercion).

    Used for every external write/delete counter shape (R07): upsert counts,
    filter-delete counts, and structured delete_by_ids counters.
    """
    if type(value) is not int:
        raise VectorDbWriteError(
            f"counter {field!r} must be a non-bool int, got "
            f"{type(value).__name__}={value!r}; fail-closed (R07)."
        )
    return value


def parse_delete_counters(result: object) -> dict[str, int]:
    """Parse a delete response into a complete counter map (R07).

    Raises:
        VectorDbWriteError: on bare int, incomplete mapping, wrong types, or bools.
    """
    if isinstance(result, bool) or type(result) is int:
        raise VectorDbWriteError(
            "delete_by_ids bare integer counters are rejected; require full "
            "{matches, successful, failed} shape (fail-closed, R07)."
        )
    if not isinstance(result, Mapping):
        # Attribute-style result objects (Weaviate DeleteManyReturn).
        data: dict[str, object] = {}
        for key in _REQUIRED_KEYS:
            if not hasattr(result, key):
                raise VectorDbWriteError(
                    f"delete counters missing required field {key!r}; "
                    "fail-closed (R07)."
                )
            data[key] = getattr(result, key)
        result = data
    # Mapping path: every key must be PRESENT (no .get defaults).
    missing = [k for k in _REQUIRED_KEYS if k not in result]
    if missing:
        raise VectorDbWriteError(
            f"delete counters missing required field(s) {missing}; "
            "fail-closed (R07)."
        )
    return {
        "matches": require_strict_int(result["matches"], field="matches"),
        "successful": require_strict_int(result["successful"], field="successful"),
        "failed": require_strict_int(result["failed"], field="failed"),
    }


def assert_delete_complete(
    counters: Mapping[str, int], *, expected: int
) -> int:
    """Require matches==successful==expected and failed==0."""
    matches = counters["matches"]
    successful = counters["successful"]
    failed = counters["failed"]
    if failed != 0 or matches != successful or successful != expected:
        raise VectorDbWriteError(
            f"partial delete: matches={matches}, successful={successful}, "
            f"failed={failed}, expected={expected}; fail-closed (R04/R07)."
        )
    return successful


__all__ = [
    "assert_delete_complete",
    "parse_delete_counters",
    "require_strict_int",
]
