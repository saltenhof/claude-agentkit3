"""Stateless I/O helpers -- atomic writes and directory utilities.

Provides crash-safe write operations used across the codebase.
Located in ``utils/`` per PROJECT_STRUCTURE.md: pure helper functions,
no business logic.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, cast

import yaml

if TYPE_CHECKING:
    from pathlib import Path


def atomic_write_text(
    path: Path,
    content: str,
    *,
    newline: str | None = None,
) -> None:
    """Write text content atomically via temporary file and ``os.replace``.

    Creates parent directories if they do not exist.  Writes to a
    temporary file first, flushes to disk, then atomically replaces
    the target file.

    Args:
        path: Destination file path.
        content: Text content to write.
        newline: Newline handling passed to ``open`` (see ``io.open``).
            Defaults to ``None`` (platform translation). Pass ``""`` to
            disable translation so the on-disk bytes equal
            ``content.encode("utf-8")`` byte-for-byte -- required where a
            digest of the written file must match a digest of *content*
            (e.g. prompt-audit byte reproducibility, FK-44 §44.6).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline=newline) as f:
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


def read_json_object(path: Path) -> dict[str, object]:
    """Read a JSON file that must hold a JSON object at the top level.

    Generic reader for harness-native or tooling JSON (for example
    ``.claude/settings.json``). This is explicitly NOT an AK3 story-export
    truth loader: it lives in ``utils.io`` (stateless helpers) so that
    protected governance / harness-adapter modules can merge harness settings
    without crossing the truth boundary
    (``formal.truth-boundary-checker.invariants`` forbids ``json.load*`` and
    AK3 export loaders inside ``agentkit.governance.*``).

    Args:
        path: JSON file to read.

    Returns:
        The parsed object as a dict, or an empty dict if *path* is absent.

    Raises:
        ValueError: If the file holds invalid JSON or a non-object top-level
            value. Fail-closed: callers must never silently overwrite a
            broken file.
    """
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in {path}: {exc}. "
            "Fail-closed: refusing to treat a broken settings file as empty."
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"JSON file {path} must contain an object, got {type(data).__name__}."
        )
    return cast("dict[str, object]", data)


def ensure_dir(path: Path) -> Path:
    """Create a directory and all parents if they do not exist.

    Args:
        path: Directory path to create.

    Returns:
        The same *path* for convenient chaining.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path
