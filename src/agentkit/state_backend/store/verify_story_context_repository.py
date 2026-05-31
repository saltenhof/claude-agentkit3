"""State-backend adapter exposing StoryContext loads as a verify-system port.

AG3-035 (echter Drift-Fix): ermoeglicht es ``verify_system.VerifySystem``, einen
``StoryContext`` aufzuloesen, ohne ``agentkit.state_backend.store`` direkt zu
importieren (BC-Topologie). Der Adapter erfuellt
``verify_system.protocols.StoryContextQueryPort`` und wird via
``bootstrap.composition_root.build_verify_system`` verdrahtet.

Analog zu ``setup_context_repository.StateBackendSetupContextAdapter`` und
``integrity_gate_repository.StateBackendIntegrityGateStateAdapter`` (Pass-5 Fix
E9): konsumierende BCs duerfen nicht selbst aus ``state_backend.store``
importieren; der Adapter kapselt den ``facade``-Aufruf.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.state_backend.store import facade

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext


class StateBackendVerifyStoryContextAdapter:
    """Adapter, der ``verify_system.protocols.StoryContextQueryPort`` erfuellt.

    Delegiert das Laden an ``facade.load_story_context``.
    """

    def load(self, story_dir: Path) -> StoryContext | None:
        """Lade den persistierten ``StoryContext`` fuer ``story_dir``.

        Args:
            story_dir: Story-Arbeitsverzeichnis.

        Returns:
            Der ``StoryContext`` oder ``None``, wenn keiner persistiert ist.
        """
        return facade.load_story_context(story_dir)
