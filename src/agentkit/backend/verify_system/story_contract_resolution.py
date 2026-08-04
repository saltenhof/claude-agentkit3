"""Story contract resolution derives QA routing contracts from the resolved StoryContext."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:

    from agentkit.backend.story_context_manager.types import (
        ImplementationContract,
        StoryType,
    )


def _effective_story_type(story_ctx: object | None) -> StoryType:
    """Return the EFFECTIVE ``StoryType`` driving both layer execution and policy.

    The resolved ``StoryContext.story_type`` drives both layer execution and
    the mandatory registry-backed policy decision. When no context resolved,
    both boundaries use the same ``IMPLEMENTATION`` execution stub. Returning
    that concrete type preserves one routing contract: the policy engine always
    resolves the explicit per-story-type threshold and performs its fail-closed
    missing-stage check for the exact type under which the layers ran.
    """
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.types import StoryType

    if isinstance(story_ctx, StoryContext):
        return story_ctx.story_type
    return StoryType.IMPLEMENTATION


def _effective_implementation_contract(
    story_ctx: object | None,
) -> ImplementationContract | None:
    """Return the EFFECTIVE ``implementation_contract`` for the policy decision.

    AG3-069 (FK-37 §37.1.3): the resolved ``StoryContext.implementation_contract``
    drives the registry-bound contract filter in ``PolicyEngine.decide``. When no
    context resolved (or it carries no contract), ``None`` is returned — the
    standard behaviour (IS stages excluded), so a non-IS run is unaffected.
    """
    from agentkit.backend.story_context_manager.models import StoryContext

    if isinstance(story_ctx, StoryContext):
        return story_ctx.implementation_contract
    return None


def _is_fast_mode(story_ctx: object | None) -> bool:
    """Whether the resolved ``StoryContext`` runs in fast mode (FK-24 §24.3.3).

    The fast/standard ``mode`` axis is decoupled from ``execution_route``
    (FK-24 §24.3.3). Returns ``False`` when no ``StoryContext`` resolved (the
    no-op port path / tests without a persisted context): a missing mode is the
    standard full-subflow default, never an accidental fast skip.

    Args:
        story_ctx: The resolved ``StoryContext`` (or ``None``).

    Returns:
        ``True`` iff a ``StoryContext`` resolved AND its ``mode`` is fast.
    """
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.story_model import WireStoryMode

    return isinstance(story_ctx, StoryContext) and story_ctx.mode is WireStoryMode.FAST
