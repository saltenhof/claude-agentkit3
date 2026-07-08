"""JSON projection primitives shared by state row mappers."""

from __future__ import annotations

import json
from typing import Any, cast

_JsonRecord = dict[str, object]


def dump_json(data: object) -> str:
    """Serialize data to a canonical JSON string."""
    return json.dumps(data, sort_keys=True, default=str)


def load_json(data: str | None, default: Any) -> Any:
    """Deserialize a JSON string, returning ``default`` when ``data`` is None."""
    if data is None:
        return default
    return json.loads(data)


def cast_json_record(value: object) -> _JsonRecord:
    """Cast an opaque value to ``dict[str, object]`` without allocation."""
    return cast("_JsonRecord", value)
