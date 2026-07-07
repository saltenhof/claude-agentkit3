"""JSON projection helpers shared by Postgres row families."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from agentkit.backend.boundary.filesystem import atomic_write_json, load_json_object

if TYPE_CHECKING:
    from pathlib import Path

_JsonRecord = dict[str, object]
_OptionalString = str | None


def load_json_safe(path: Path) -> _JsonRecord | None:
    """Compatibility helper for non-canonical export reads."""

    return load_json_object(path)


def _write_projection(path: Path, payload: _JsonRecord) -> None:
    """Atomically write a JSON projection file, creating parent dirs as needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


def _dump_json(data: object) -> str:
    return json.dumps(data, sort_keys=True, default=str)


def _load_json(data: str | None, default: Any) -> Any:
    if data is None:
        return default
    return json.loads(data)


def _cast_json_record(value: object) -> _JsonRecord:
    return cast("_JsonRecord", value)


def _cast_optional_str(value: object) -> _OptionalString:
    return cast("_OptionalString", value)
