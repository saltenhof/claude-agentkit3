"""Strict MCP tool argument contracts (FK-13 §13.4.1 / §13.9.5, AC 10).

Fail-closed: no bool-as-int coercion, no enum coercion, no silent defaults
beyond the documented optional defaults.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

SEARCH_MODES: Final[frozenset[str]] = frozenset({"hybrid", "vector", "keyword"})
CONCEPT_STATUSES: Final[frozenset[str]] = frozenset({"active", "draft", "archived"})
DEFAULT_SEARCH_LIMIT: Final[int] = 10
MAX_SEARCH_LIMIT: Final[int] = 100

TOOL_NAMES: Final[tuple[str, ...]] = (
    "story_search",
    "story_list_sources",
    "story_sync",
    "concept_search",
    "concept_sync",
)


class ToolArgumentError(Exception):
    """Raised when a tool argument fails strict validation."""

    def __init__(self, message: str, *, field: str = "") -> None:
        self.field = field
        super().__init__(message)


def require_str(args: Mapping[str, Any], key: str, *, required: bool = True) -> str | None:
    if key not in args or args[key] is None:
        if required:
            raise ToolArgumentError(f"missing required string argument {key!r}", field=key)
        return None
    value = args[key]
    if not isinstance(value, str):
        raise ToolArgumentError(
            f"{key!r} must be a string, got {type(value).__name__}",
            field=key,
        )
    return value


def optional_str(args: Mapping[str, Any], key: str) -> str | None:
    return require_str(args, key, required=False)


def require_bool(args: Mapping[str, Any], key: str, *, default: bool | None = None) -> bool:
    if key not in args or args[key] is None:
        if default is None:
            raise ToolArgumentError(f"missing required boolean argument {key!r}", field=key)
        return default
    value = args[key]
    if not isinstance(value, bool):
        raise ToolArgumentError(
            f"{key!r} must be a boolean (no int coercion), got {type(value).__name__}",
            field=key,
        )
    return value


def require_limit(args: Mapping[str, Any], key: str = "limit") -> int:
    if key not in args or args[key] is None:
        return DEFAULT_SEARCH_LIMIT
    value = args[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolArgumentError(
            f"{key!r} must be an int (no bool coercion), got {type(value).__name__}",
            field=key,
        )
    if value <= 0 or value > MAX_SEARCH_LIMIT:
        raise ToolArgumentError(
            f"{key!r} must be in 1..{MAX_SEARCH_LIMIT}, got {value}",
            field=key,
        )
    return value


def require_search_mode(args: Mapping[str, Any]) -> str:
    if "search_mode" not in args or args["search_mode"] is None:
        return "hybrid"
    value = args["search_mode"]
    if not isinstance(value, str) or value not in SEARCH_MODES:
        raise ToolArgumentError(
            f"search_mode must be one of {sorted(SEARCH_MODES)}, got {value!r}",
            field="search_mode",
        )
    return value


def require_concept_status(args: Mapping[str, Any]) -> str:
    if "concept_status" not in args or args["concept_status"] is None:
        return "active"
    value = args["concept_status"]
    if not isinstance(value, str) or value not in CONCEPT_STATUSES:
        raise ToolArgumentError(
            f"concept_status must be one of {sorted(CONCEPT_STATUSES)}, got {value!r}",
            field="concept_status",
        )
    return value


def optional_bool(args: Mapping[str, Any], key: str) -> bool | None:
    if key not in args or args[key] is None:
        return None
    value = args[key]
    if not isinstance(value, bool):
        raise ToolArgumentError(
            f"{key!r} must be a boolean, got {type(value).__name__}",
            field=key,
        )
    return value


__all__ = [
    "CONCEPT_STATUSES",
    "DEFAULT_SEARCH_LIMIT",
    "MAX_SEARCH_LIMIT",
    "SEARCH_MODES",
    "TOOL_NAMES",
    "ToolArgumentError",
    "optional_bool",
    "optional_str",
    "require_bool",
    "require_concept_status",
    "require_limit",
    "require_search_mode",
    "require_str",
]
