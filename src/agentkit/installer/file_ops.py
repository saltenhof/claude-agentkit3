"""Installer-scoped file operation helpers."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from agentkit.exceptions import ProjectError
from agentkit.utils.io import atomic_write_text, atomic_write_yaml, ensure_dir

if TYPE_CHECKING:
    from pathlib import Path


def create_or_replace_hardlink(source: Path, target: Path) -> None:
    """Create a file hardlink, replacing an existing target if needed."""

    if not source.is_file():
        raise ProjectError(
            f"Hardlink source does not exist: {source}",
            detail={"source": str(source), "target": str(target)},
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()

    try:
        os.link(source, target)
    except OSError as exc:
        raise ProjectError(
            f"Failed to create hardlink from {source} to {target}: {exc}",
            detail={"source": str(source), "target": str(target), "error": str(exc)},
        ) from exc

__all__ = [
    "atomic_write_text",
    "atomic_write_yaml",
    "create_or_replace_hardlink",
    "ensure_dir",
]
