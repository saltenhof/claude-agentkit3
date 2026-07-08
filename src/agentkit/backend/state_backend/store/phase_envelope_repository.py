"""StateBackendPhaseEnvelopeRepository -- concrete PhaseEnvelopeRepository.

Adapts the existing state_backend facade (load_phase_state /
save_phase_state) to the PhaseEnvelopeRepository protocol.

The current backend API is story_dir-based; this class holds a reference
to the story_dir and delegates to the existing facade functions.  No new
DB schema is introduced -- persistence continues to use the
``phase_states`` table (or SQLite equivalent) unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.pipeline_runtime_store import (
    load_phase_state,
    save_phase_state,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.pipeline_engine.phase_executor import PhaseName, PhaseState


class StateBackendPhaseEnvelopeRepository:
    """Concrete PhaseEnvelopeRepository backed by the state_backend facade.

    Satisfies the ``PhaseEnvelopeRepository`` Protocol.

    The ``story_dir`` is the canonical story artifact directory (used by
    all existing backend I/O). The ``load_state`` / ``save_state`` /
    ``exists_state`` methods delegate to the existing
    ``load_phase_state`` / ``save_phase_state`` facade calls without
    introducing any new persistence schema.

    Args:
        story_dir: The story artifact directory (e.g.
            ``project_root/stories/AG3-123``).
    """

    def __init__(self, story_dir: Path) -> None:
        self._story_dir = story_dir

    def load_state(
        self,
        story_id: str,
        phase: PhaseName,
    ) -> PhaseState | None:
        """Load the latest persisted PhaseState for (story_id, phase).

        The ``phase`` argument is accepted for protocol compatibility but
        the underlying SQLite/Postgres backend stores exactly one current
        phase state per story_dir (the most-recently-saved one). The
        caller is responsible for ensuring the loaded state matches the
        expected phase.

        Args:
            story_id: Story identifier (used for validation only; the
                physical key is ``story_dir``).
            phase: Pipeline phase name (protocol parameter; not used as a
                secondary index in the current schema).

        Returns:
            The persisted ``PhaseState``, or ``None`` if not found.
        """
        _ = story_id, phase  # story_dir is the physical key
        return load_phase_state(self._story_dir)

    def save_state(self, state: PhaseState) -> None:
        """Persist a PhaseState via the existing facade.

        Args:
            state: The phase state to persist.
        """
        save_phase_state(self._story_dir, state)

    def exists_state(self, story_id: str, phase: PhaseName) -> bool:
        """Return True if a PhaseState is present in storage.

        Args:
            story_id: Story identifier (protocol parameter; not used
                directly -- the physical key is ``story_dir``).
            phase: Pipeline phase name (protocol parameter).

        Returns:
            ``True`` if a state record exists, ``False`` otherwise.
        """
        _ = story_id, phase
        return load_phase_state(self._story_dir) is not None
