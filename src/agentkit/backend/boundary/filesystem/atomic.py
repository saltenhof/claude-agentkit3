"""Atomic filesystem write helpers for JSON artifacts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.backend.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path


def atomic_write_json(path: Path, data: dict[str, object]) -> None:
    """Write a dictionary as JSON atomically.

    Serialises *data* as JSON (sorted keys, 2-space indent) and writes the
    result via :func:`agentkit.backend.utils.io.atomic_write_text` so that no
    partial file is ever visible to concurrent readers.

    Args:
        path: Destination file path.
        data: Dictionary to serialise as JSON.
    """
    atomic_write_text(
        path,
        json.dumps(data, indent=2, sort_keys=True, default=str),
    )
