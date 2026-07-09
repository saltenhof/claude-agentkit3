"""Requirements-coverage persistence store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.requirements_coverage.models import (
        StoryAreLink,
        StoryAreLinkKind,
    )


def save_story_are_link(
    link: StoryAreLink,
    store_dir: Path | None = None,
) -> None:
    """Persist one StoryAreLink edge."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    row = mappers.story_are_link_to_row(link)
    _backend_module().save_story_are_link_row(store_dir, row)


def load_story_are_links(
    story_id: str,
    store_dir: Path | None = None,
) -> list[StoryAreLink]:
    """Load StoryAreLink edges for one story."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    rows = _backend_module().load_story_are_link_rows(store_dir, story_id)
    return [mappers.story_are_link_row_to_entity(row) for row in rows]


def update_story_are_link_kind(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    old_kind: StoryAreLinkKind,
    new_kind: StoryAreLinkKind,
) -> StoryAreLink | None:
    """Update one StoryAreLink edge kind."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    row = _backend_module().update_story_are_link_kind_row(
        store_dir,
        story_id,
        are_item_id,
        old_kind.value,
        new_kind.value,
    )
    if row is None:
        return None
    return mappers.story_are_link_row_to_entity(row)


def delete_story_are_link(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    kind: StoryAreLinkKind,
) -> int:
    """Delete one StoryAreLink edge."""
    return int(
        _backend_module().delete_story_are_link_row(
            store_dir,
            story_id,
            are_item_id,
            kind.value,
        ),
    )


__all__ = [
    "save_story_are_link",
    "load_story_are_links",
    "update_story_are_link_kind",
    "delete_story_are_link",
]
