"""Template selection based on story type, mode, and spawn reason."""

from __future__ import annotations

from agentkit.story.types import StoryMode, StoryType

# Mapping from StoryType to template name for the default case.
_TYPE_TO_TEMPLATE: dict[StoryType, str] = {
    StoryType.IMPLEMENTATION: "worker-implementation",
    StoryType.BUGFIX: "worker-bugfix",
    StoryType.CONCEPT: "worker-concept",
    StoryType.RESEARCH: "worker-research",
}


def select_template_name(
    story_type: StoryType,
    mode: StoryMode | None = None,
    spawn_reason: str = "initial",
) -> str:
    """Select the appropriate template name.

    Selection rules (evaluated in order of priority):

    1. ``spawn_reason == "remediation"`` always selects
       ``"worker-remediation"``.
    2. ``mode == EXPLORATION`` (and *spawn_reason* is not
       ``"remediation"``) selects ``"worker-exploration"``.
    3. Otherwise the *story_type* determines the template via the
       standard type-to-template mapping.

    Args:
        story_type: The type of story being processed.
        mode: Execution mode (execution, exploration, not_applicable).
        spawn_reason: Why the worker is being spawned.  Defaults to
            ``"initial"``.

    Returns:
        Template name string (key into the ``TEMPLATES`` dict).

    Raises:
        ValueError: If no template matches the given *story_type*.
    """
    # Rule 1: remediation always wins
    if spawn_reason == "remediation":
        return "worker-remediation"

    # Rule 2: exploration mode overrides story type
    if mode == StoryMode.EXPLORATION:
        return "worker-exploration"

    # Rule 3: standard type mapping
    template_name = _TYPE_TO_TEMPLATE.get(story_type)
    if template_name is None:
        msg = f"No template registered for story type: {story_type!r}"
        raise ValueError(msg)

    return template_name
