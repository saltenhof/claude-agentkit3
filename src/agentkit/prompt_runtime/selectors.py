"""Template selection based on story type, execution route, and spawn reason.

``spawn_reason`` ist seit AG3-021 ein typisiertes ``SpawnReason``-Enum
(``agentkit.core_types``) statt eines freien Strings. Aufrufer muessen
ein ``SpawnReason``-Member uebergeben.
"""

from __future__ import annotations

from agentkit.core_types import SpawnReason
from agentkit.story_context_manager.types import StoryMode, StoryType

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
        story_type: Story-Typ-Kennzeichen aus ``StoryContext``.
        execution_route: Story-Mode-Route (Implementation-Pfad).
        mode: Legacy-Alias fuer ``execution_route``; bleibt aus
            Kompatibilitaet bestehen.
        spawn_reason: ``SpawnReason``-Enum, das die aktuelle
            Spawn-Phase klassifiziert (``INITIAL`` / ``PAUSED_RETRY``
            / ``REMEDIATION``). Pflicht: typisiertes Enum.

    Returns:
        Der Name der Worker-Prompt-Vorlage.
    """
    route = execution_route if execution_route is not None else mode

    # Fail-closed runtime guard (AG3-021 §AC11): SpawnReason muss
    # zur Laufzeit ein echtes Enum-Member sein. Freie Strings wuerden
    # an der ``is``-Pruefung still vorbeilaufen und auf den falschen
    # Pfad routen.
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
