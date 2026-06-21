"""Single source of truth for Story display-ID formatting.

FK-02 §2.11.2: the Story display-ID (e.g. ``AK3-042``) is a derived
**presentation** of the canonical identity ``(project_key, story_number)``.
It is materialized exactly once at story creation and persisted as a plain
string field. This module owns the one and only formatting rule so that every
materialization site produces an identical format and no drift can creep in.

Padding is a presentation concern only: the number is rendered with a minimum
width of three digits (``story_number=42 -> "AK3-042"``). It is a *minimum*,
not a maximum — numbers ``>= 1000`` render wider automatically
(``story_number=1000 -> "AK3-1000"``). There is no maximum width and no
dynamic width computation.

Sorting is **never** lexicographic over the display-ID (that would order
``AK3-1000`` before ``AK3-999``). Sorting is always numeric over
``story_number`` (an ``int``); see ``StoryRepository.list_for_project`` and
``execution_planning.readiness``.
"""

from __future__ import annotations

#: Minimum zero-padded width of the numeric suffix (FK-02 §2.11.2). This is a
#: *minimum* — larger numbers render wider; there is no maximum.
DISPLAY_ID_MIN_WIDTH = 3


def format_story_display_id(prefix: str, story_number: int) -> str:
    """Return the canonical Story display-ID string.

    This is the single source of truth for display-ID materialization
    (FK-02 §2.11.2). All call sites that persist a ``story_display_id`` /
    ``story_id`` MUST go through this function.

    Args:
        prefix: The project's immutable ``story_id_prefix`` (e.g. ``"AK3"``).
        story_number: The project-local, monotonically increasing story
            number. Must be ``>= 1``.

    Returns:
        The display-ID with a minimum-three-digit zero-padded suffix, e.g.
        ``format_story_display_id("AK3", 42) == "AK3-042"`` and
        ``format_story_display_id("AK3", 1000) == "AK3-1000"``.

    Raises:
        ValueError: If ``story_number`` is below 1 (fail-closed: a display-ID
            cannot be materialized before a valid number was allocated).
    """
    if story_number < 1:
        raise ValueError(
            f"story_number must be >= 1 to materialize a display-ID, "
            f"got {story_number!r}",
        )
    return f"{prefix}-{story_number:0{DISPLAY_ID_MIN_WIDTH}d}"


__all__ = ["DISPLAY_ID_MIN_WIDTH", "format_story_display_id"]
