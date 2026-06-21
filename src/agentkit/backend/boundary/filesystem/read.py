"""Read-side filesystem helpers for projection JSON objects.

Boundary kind: infrastructure_io
Blood group:   R
Importable by: any
May import:    boundary.shared
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def load_json_object(path: Path) -> dict[str, object] | None:
    """Load a JSON object from *path*, returning None on absence or invalid content."""

    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def read_projection_json_object(path: Path) -> dict[str, object] | None:
    """Read a projection JSON object outside runtime truth paths."""

    return load_json_object(path)
