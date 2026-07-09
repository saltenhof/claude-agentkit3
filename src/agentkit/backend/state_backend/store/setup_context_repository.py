"""StateBackendSetupContextAdapter — SetupContextRepository implementation.

Implements ``agentkit.backend.governance.repository.SetupContextRepository`` using
the canonical ``state-backend owner modules.save_story_context`` function.
This keeps ``agentkit.backend.governance.setup_preflight_gate.phase`` decoupled
from the state backend (Architecture Conformance Fix E9, AG3-031 Pass-4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.story_lifecycle_store import save_story_context

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.story_context_manager.models import StoryContext


class StateBackendSetupContextAdapter:
    """Adapter from ``state-backend owner modules`` to ``SetupContextRepository``.

    Delegates the single ``save`` call to ``save_story_context``.
    No business logic lives here.

    This class intentionally does not inherit from the Protocol class — it
    satisfies the structural (duck-typed) Protocol without formal inheritance,
    which avoids an import of ``agentkit.backend.governance.repository`` from this
    module (direction: state_backend -> governance would be a layering
    violation).
    """

    def save(self, story_dir: Path, ctx: StoryContext) -> None:
        """Persist ``ctx`` via ``save_story_context``.

        Args:
            story_dir: Story base directory (scopes the write).
            ctx: The ``StoryContext`` to persist.

        Raises:
            Exception: On unrecoverable backend failures.
        """
        save_story_context(story_dir, ctx)


__all__ = ["StateBackendSetupContextAdapter"]
