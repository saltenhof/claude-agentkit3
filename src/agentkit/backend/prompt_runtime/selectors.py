"""Template selection based on story type, execution route, and spawn reason.

``spawn_reason`` is, since AG3-021, a typed ``SpawnReason`` enum
(``agentkit.backend.core_types``) instead of a free string. Callers must pass a
``SpawnReason`` member.
"""

from __future__ import annotations

from agentkit.backend.core_types import SpawnReason
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

_TYPE_TO_TEMPLATE: dict[StoryType, str] = {
    StoryType.IMPLEMENTATION: "worker-implementation",
    StoryType.BUGFIX: "worker-bugfix",
    StoryType.CONCEPT: "worker-concept",
    StoryType.RESEARCH: "worker-research",
}


def select_template_name(
    story_type: StoryType,
    execution_route: StoryMode | None = None,
    *,
    mode: StoryMode | None = None,
    spawn_reason: SpawnReason = SpawnReason.INITIAL,
) -> str:
    """Resolve the worker prompt template name for the given context.

    Args:
        story_type: Story-type marker from ``StoryContext``.
        execution_route: Story-mode route (implementation path).
        mode: Legacy alias for ``execution_route``; kept for
            compatibility.
        spawn_reason: ``SpawnReason`` enum classifying the current
            spawn phase (``INITIAL`` / ``PAUSED_RETRY``
            / ``REMEDIATION``). Mandatory: typed enum.

    Returns:
        The name of the worker prompt template.
    """
    route = execution_route if execution_route is not None else mode

    # Fail-closed runtime guard (AG3-021 §AC11): SpawnReason must be a
    # real enum member at runtime. Free strings would silently slip past
    # the ``is`` check and route onto the wrong path.
    if not isinstance(spawn_reason, SpawnReason):
        msg = (
            f"spawn_reason must be SpawnReason, got "
            f"{type(spawn_reason).__name__!r}: {spawn_reason!r}"
        )
        raise TypeError(msg)

    if spawn_reason is SpawnReason.REMEDIATION:
        return "worker-remediation"

    if route == StoryMode.EXPLORATION:
        return "worker-exploration"

    template_name = _TYPE_TO_TEMPLATE.get(story_type)
    if template_name is None:
        msg = f"No template registered for story type: {story_type!r}"
        raise ValueError(msg)

    return template_name


__all__ = ["select_template_name"]
