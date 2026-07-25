"""Batch ``story.md`` repair (FK-21 §21.11.6).

``repair-story-md`` scans ``stories/{prefix}-*/story.md`` directories, derives
the story-ID from the directory name, validates each existing ``story.md`` and
re-exports defective / missing files deterministically. The report is the
``(N checked, M repaired, K errors)`` triple.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.story_creation.story_md_export import (
    MIN_STORY_MD_BYTES,
    STORY_DIR_RE,
    STORY_MD_FILENAME,
    _validate_frontmatter,
    export_story_md,
    story_dir_story_id,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.story_creation.story_md_export import (
        StoryAttributesPort,
        StoryIndexPort,
    )

#: A story directory is ``{PREFIX}-{number}`` optionally followed by a slug.
#: ONE definition, shared with the export (``story_md_export.STORY_DIR_RE``) so
#: both agree on which directory belongs to which story.
_STORY_DIR_RE = STORY_DIR_RE


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
    return story_dir_story_id(directory.name)


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
    project_id: str,
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
            project_id=project_id,
            # The project root of a ``<project>/stories/`` corpus root (N31): the
            # export validates containment against it before writing anything.
            project_root=stories_root.parent,
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
