"""SQLite state-backend JSON projection and path helpers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from agentkit.backend.boundary.filesystem import atomic_write_json, load_json_object
from agentkit.backend.state_backend.config import versioned_sqlite_db_file
from agentkit.backend.state_backend.paths import state_backend_dir

if TYPE_CHECKING:
    from pathlib import Path

_JsonRecord = dict[str, object]

def current_db_file_name() -> str:
    """Return the versioned SQLite database filename used by this driver."""

    return versioned_sqlite_db_file()


def state_db_path_for(story_dir: Path) -> Path:
    """Return the versioned SQLite database path used by this driver."""

    return state_backend_dir(story_dir) / current_db_file_name()


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
