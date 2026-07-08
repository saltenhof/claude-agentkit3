"""JSON record typing and JSON boundary helpers for persistence code."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
)

if TYPE_CHECKING:
    from pathlib import Path

JsonRecord = dict[str, object]


def dump_json(data: object) -> str:
    """Serialize data to a canonical JSON string."""
    return json.dumps(data, sort_keys=True, default=str)


def load_json(data: str | None, default: Any) -> Any:
    """Deserialize a JSON string, returning ``default`` when ``data`` is None."""
    if data is None:
        return default
    return json.loads(data)


def cast_json_record(value: object) -> JsonRecord:
    """Cast an opaque value to ``dict[str, object]`` without allocation."""
    return cast("JsonRecord", value)


def _cast_json_record(value: object) -> JsonRecord | None:
    return cast("JsonRecord | None", value)


def load_json_safe(path: Path) -> JsonRecord | None:
    """Load one JSON record through the active state backend."""
    return _cast_json_record(_backend_module().load_json_safe(path))


__all__ = [
    "JsonRecord",
    "dump_json",
    "load_json",
    "cast_json_record",
    "load_json_safe",
]
