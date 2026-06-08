"""Story context component namespace."""

from __future__ import annotations

from importlib import import_module

from agentkit.story_context_manager.display_id import format_story_display_id
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.routing_rules import get_phases_for_story
from agentkit.story_context_manager.sizing import StorySize
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
    StoryTypeProfile,
    get_profile,
)

_PHASE_MODEL_BRIDGE = {"PhaseSnapshot", "PhaseState", "PhaseStatus"}


def __getattr__(name: str) -> object:
    if name in _PHASE_MODEL_BRIDGE:
        phase_executor = import_module("agentkit.pipeline_engine.phase_executor")
        return getattr(phase_executor, name)
    raise AttributeError(name)


__all__ = [
    # Deprecated compatibility bridge. Phase-state model ownership is
    # agentkit.pipeline_engine.phase_executor (FK-39 §39.7).
    "PhaseSnapshot",
    "PhaseState",
    "PhaseStatus",
    "ImplementationContract",
    "StoryContext",
    "StoryMode",
    "StorySize",
    "StoryType",
    "StoryTypeProfile",
    "format_story_display_id",
    "get_phases_for_story",
    "get_profile",
]
