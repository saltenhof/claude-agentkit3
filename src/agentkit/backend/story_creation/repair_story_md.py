"""Batch ``story.md`` repair (FK-21 §21.11.6).

``repair-story-md`` scans ``stories/{prefix}-*/story.md`` directories, derives
the story-ID from the directory name, validates each existing ``story.md`` and
re-exports defective / missing files deterministically. The report is the
``(N checked, M repaired, K errors)`` triple.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.story_creation.story_md_export import (
    MIN_STORY_MD_BYTES,
    STORY_MD_FILENAME,
    _validate_frontmatter,
    export_story_md,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.story_creation.story_md_export import (
        StoryAttributesPort,
        StoryIndexPort,
    )

#: A story directory is ``{PREFIX}-{number}`` optionally followed by ``_slug``.
_STORY_DIR_RE = re.compile(r"^(?P<story_id>[A-Z][A-Z0-9]{1,9}-\d+)(?:[_-].*)?$")


@dataclass(frozen=True)
class RepairReport:
    """The ``repair-story-md`` outcome (FK-21 §21.11.6).

    Attributes:
        checked: N -- number of story directories scanned.
        repaired: M -- number of ``story.md`` files (re)exported successfully.
        errors: K -- number of directories where the re-export failed.
        error_details: Per-story error messages for the K failures.
    """

    checked: int
    repaired: int
    errors: int
    error_details: dict[str, str]


def _story_id_from_dir(directory: Path) -> str | None:
    """Derive the story display-ID from a story directory name."""
    match = _STORY_DIR_RE.match(directory.name)
    return match.group("story_id") if match else None


def _needs_repair(story_md: Path) -> bool:
    """Return whether an existing ``story.md`` is missing / invalid."""
    if not story_md.is_file():
        return True
    try:
        size = story_md.stat().st_size
    except OSError:
        return True
    if size <= MIN_STORY_MD_BYTES:
        return True
    try:
        text = story_md.read_text(encoding="utf-8")
    except OSError:
        return True
    return _validate_frontmatter(text) is not None


def repair_story_md(
    stories_root: Path,
    *,
    story_attributes: StoryAttributesPort,
    index: StoryIndexPort,
) -> RepairReport:
    """Scan, validate and re-export defective / missing ``story.md`` files.

    Args:
        stories_root: The ``stories/`` directory holding story sub-directories.
        story_attributes: Authoritative story-attribute read surface.
        index: Incremental Weaviate indexing surface (hard blocker per export).

    Returns:
        A :class:`RepairReport` with the ``(N, M, K)`` triple.
    """
    checked = 0
    repaired = 0
    error_details: dict[str, str] = {}

    for directory in sorted(p for p in stories_root.iterdir() if p.is_dir()):
        story_id = _story_id_from_dir(directory)
        if story_id is None:
            continue
        checked += 1
        story_md = directory / STORY_MD_FILENAME
        if not _needs_repair(story_md):
            continue
        result = export_story_md(
            story_id,
            directory,
            story_attributes=story_attributes,
            index=index,
        )
        if result.success:
            repaired += 1
        else:
            error_details[story_id] = result.error

    return RepairReport(
        checked=checked,
        repaired=repaired,
        errors=len(error_details),
        error_details=error_details,
    )


__all__ = [
    "RepairReport",
    "repair_story_md",
]
