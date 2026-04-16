"""Template selection based on story type, mode, and spawn reason."""

from __future__ import annotations

from agentkit.story_context_manager.types import StoryMode, StoryType

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
    if spawn_reason == "remediation":
        return "worker-remediation"

    if mode == StoryMode.EXPLORATION:
        return "worker-exploration"

    template_name = _TYPE_TO_TEMPLATE.get(story_type)
    if template_name is None:
        msg = f"No template registered for story type: {story_type!r}"
        raise ValueError(msg)

    return template_name

__all__ = ["select_template_name"]
