"""SQLite story identity helper functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _disambiguated_story_prefix(prefix: str, project_key: str) -> str:
    suffix = "".join(ch for ch in project_key.upper() if ch.isalnum())[:6]
    if not suffix:
        suffix = "X"
    return f"{prefix[: max(1, 10 - len(suffix))]}{suffix}"[:10]


def _story_number_from_id(story_id: str) -> int | None:
    suffix = story_id.rsplit("-", maxsplit=1)[-1]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _story_id_for(story_dir: Path) -> str | None:
    return story_dir.name or None
