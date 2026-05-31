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

from agentkit.exceptions import CorruptStateError
from agentkit.state_backend.store import facade
from agentkit.verify_system.protocols import RunScope

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext


class StateBackendVerifyStoryContextAdapter:
    """Adapter, der ``verify_system.protocols.StoryContextQueryPort`` erfuellt.

    Delegiert das Laden an ``facade.load_story_context`` und die
    Run-Korrelation an ``facade.resolve_runtime_scope`` (AG3-015, FK-44
    §44.4.2). Konsumierende BCs duerfen nicht selbst aus
    ``state_backend.store`` importieren; dieser Adapter kapselt den
    ``facade``-Aufruf.
    """

    def load(self, story_dir: Path) -> StoryContext | None:
        """Lade den persistierten ``StoryContext`` fuer ``story_dir``.

        Args:
            story_dir: Story-Arbeitsverzeichnis.

        Returns:
            Der ``StoryContext`` oder ``None``, wenn keiner persistiert ist.
        """
        return facade.load_story_context(story_dir)

    def resolve_run_scope(self, story_dir: Path) -> RunScope | None:
        """Loese die Run-Korrelation (run_id, story_id, attempt) auf.

        Args:
            story_dir: Story-Arbeitsverzeichnis.

        Returns:
            Ein ``RunScope`` oder ``None``, wenn keine eindeutige
            Run-Korrelation aufloesbar ist (kein Flow-/Context-State oder
            kein ``run_id``); dann wird der Prompt-Audit uebersprungen.
        """
        try:
            scope = facade.resolve_runtime_scope(story_dir)
        except CorruptStateError:
            return None
        if scope.run_id is None:
            return None
        return RunScope(
            run_id=scope.run_id,
            story_id=scope.story_id,
            attempt=scope.attempt_no or 1,
        )
