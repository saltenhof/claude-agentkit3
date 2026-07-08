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

    FIX-A (fail-closed): the production path must never re-enter the policy
    engine's scalar fallback (which runs NO registry-bound missing-stage check,
    FK-33 §33.7 -- a fail-open edge). The effective story type is the SAME one
    ``_execute_layer`` commits to: the resolved ``StoryContext.story_type`` when
    a context resolved, otherwise the ``IMPLEMENTATION`` stub used for the layer
    run itself. Returning a concrete type unconditionally guarantees
    ``PolicyEngine.decide`` always takes the registry path (per-story-type
    threshold FK-33 §33.7.3 + fail-closed missing-stage check), consistent with
    the type the layers were evaluated under. There is no genuinely-unknown
    story type on this path: layer execution already chose IMPLEMENTATION when
    unresolved, so the policy decision uses the identical effective type rather
    than silently downgrading to the scalar threshold.
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
