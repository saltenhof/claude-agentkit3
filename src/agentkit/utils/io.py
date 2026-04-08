"""Stateless I/O helpers -- atomic writes and directory utilities.

Provides crash-safe write operations used across the codebase.
Located in ``utils/`` per PROJECT_STRUCTURE.md: pure helper functions,
no business logic.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """Write text content atomically via temporary file and ``os.replace``.

    Creates parent directories if they do not exist.  Writes to a
    temporary file first, flushes to disk, then atomically replaces
    the target file.

    Args:
        path: Destination file path.
        content: Text content to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(path))
    except BaseException:
        # Clean up temp file on any failure
        if tmp.exists():
            tmp.unlink()
        raise


def atomic_write_yaml(path: Path, data: dict[str, object]) -> None:
    """Write a dictionary as YAML atomically.

    Args:
        path: Destination file path.
        data: Dictionary to serialise as YAML.
    """
    content = yaml.dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    atomic_write_text(path, content)


def ensure_dir(path: Path) -> Path:
    """Create a directory and all parents if they do not exist.

    Args:
        path: Directory path to create.

    Returns:
        The same *path* for convenient chaining.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path
