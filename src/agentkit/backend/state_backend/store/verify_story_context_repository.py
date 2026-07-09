"""State-backend adapter exposing StoryContext loads as a verify-system port.

AG3-035 (real drift fix): lets ``verify_system.VerifySystem`` resolve a
``StoryContext`` without importing ``agentkit.backend.state_backend.store`` directly
(BC topology). The adapter satisfies
``verify_system.protocols.StoryContextQueryPort`` and is wired via
``bootstrap.composition_root.build_verify_system``.

Analogous to ``setup_context_repository.StateBackendSetupContextAdapter`` and
``integrity_gate_repository.StateBackendIntegrityGateStateAdapter`` (Pass-5 fix
E9): consuming BCs may not import from ``state_backend.store`` themselves;
the adapter encapsulates the ``facade`` call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend.runtime_scope_resolver import resolve_runtime_scope
from agentkit.backend.state_backend.story_lifecycle_store import load_story_context
from agentkit.backend.verify_system.protocols import RunScope

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.story_context_manager.models import StoryContext


class StateBackendVerifyStoryContextAdapter:
    """Adapter satisfying ``verify_system.protocols.StoryContextQueryPort``.

    Delegates loading to ``load_story_context`` and the
    run correlation to ``resolve_runtime_scope`` (AG3-015, FK-44
    §44.4.2). Consuming BCs may not import from
    ``state_backend.store`` themselves; this adapter encapsulates the
    ``facade`` call.
    """

    def load(self, story_dir: Path) -> StoryContext | None:
        """Load the persisted ``StoryContext`` for ``story_dir``.

        Args:
            story_dir: Story working directory.

        Returns:
            The ``StoryContext`` or ``None`` when none is persisted.
        """
        return load_story_context(story_dir)

    def resolve_run_scope(self, story_dir: Path) -> RunScope | None:
        """Resolve the run correlation (run_id, story_id, attempt).

        Args:
            story_dir: Story working directory.

        Returns:
            A ``RunScope`` or ``None`` when no unique
            run correlation is resolvable (no flow/context state or
            no ``run_id``); then the prompt audit is skipped.
        """
        try:
            scope = resolve_runtime_scope(story_dir)
        except CorruptStateError:
            return None
        if scope.run_id is None:
            return None
        return RunScope(
            run_id=scope.run_id,
            story_id=scope.story_id,
            attempt=scope.attempt_no or 1,
        )
