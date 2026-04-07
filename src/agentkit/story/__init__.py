"""Story domain -- pure business logic for GitHub Issue modeling.

This package defines what a "story" (GitHub Issue) is in AgentKit:
its type, sizing, execution mode, context, phase state, and the
routing rules that determine which pipeline phases it goes through.

No external dependencies -- pure domain logic only.
"""

from __future__ import annotations

from agentkit.story.models import PhaseSnapshot, PhaseState, PhaseStatus, StoryContext
from agentkit.story.routing_rules import get_phases_for_story
from agentkit.story.sizing import StorySize
from agentkit.story.types import StoryMode, StoryType, StoryTypeProfile, get_profile

__all__ = [
    "PhaseSnapshot",
    "PhaseState",
    "PhaseStatus",
    "StoryContext",
    "StoryMode",
    "StorySize",
    "StoryType",
    "StoryTypeProfile",
    "get_phases_for_story",
    "get_profile",
]
