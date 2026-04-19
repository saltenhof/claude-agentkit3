"""Installer-scoped file operation helpers."""

from __future__ import annotations

import errno
import os
import shutil
from typing import TYPE_CHECKING

from agentkit.exceptions import ProjectError
from agentkit.utils.io import atomic_write_text, atomic_write_yaml, ensure_dir

if TYPE_CHECKING:
    from pathlib import Path


def create_or_replace_hardlink(source: Path, target: Path) -> None:
    """Create prompt projection via hardlink, symlink, or last-resort copy."""

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
        if _can_fallback_to_symlink(exc):
            try:
                os.symlink(source, target)
                return
            except OSError as symlink_exc:
                if _can_fallback_to_copy(symlink_exc):
                    try:
                        shutil.copy2(source, target)
                        return
                    except OSError as copy_exc:
                        raise ProjectError(
                            "Failed to create prompt projection "
                            f"from {source} to {target}: {copy_exc}",
                            detail={
                                "source": str(source),
                                "target": str(target),
                                "error": str(copy_exc),
                            },
                        ) from copy_exc
                raise ProjectError(
                    "Failed to create prompt binding "
                    f"from {source} to {target}: {symlink_exc}",
                    detail={
                        "source": str(source),
                        "target": str(target),
                        "error": str(symlink_exc),
                    },
                ) from symlink_exc
        raise ProjectError(
            f"Failed to create hardlink from {source} to {target}: {exc}",
            detail={"source": str(source), "target": str(target), "error": str(exc)},
        ) from exc


def _can_fallback_to_symlink(exc: OSError) -> bool:
    return (
        exc.errno == errno.EXDEV
        or getattr(exc, "winerror", None) == 17
    )


def _can_fallback_to_copy(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) == 1314


def copy_file(source: Path, target: Path) -> None:
    """Copy a file, creating parent directories as needed."""

    if not source.is_file():
        raise ProjectError(
            f"Copy source does not exist: {source}",
            detail={"source": str(source), "target": str(target)},
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, target)
    except OSError as exc:
        raise ProjectError(
            f"Failed to copy file from {source} to {target}: {exc}",
            detail={"source": str(source), "target": str(target), "error": str(exc)},
        ) from exc

__all__ = [
    "atomic_write_text",
    "atomic_write_yaml",
    "copy_file",
    "create_or_replace_hardlink",
    "ensure_dir",
]
