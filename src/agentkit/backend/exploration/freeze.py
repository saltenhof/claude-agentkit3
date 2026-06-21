"""DesignFreezeMarker -- freeze the change-frame after a PASS gate (FK-23 §23.4.3).

FK-23 §23.4.3 / FK-25 §25.4.2: the change-frame is editable throughout doc
fidelity, review, challenge, nachklassifikation and fine-design; only AFTER the
exit-gate PASSES is it frozen. The freeze:

1. sets ``frozen: true`` (and ``frozen_at``) on the change-frame;
2. (re-)writes the protected ``_temp/qa/{story_id}/change_frame.json`` file;
3. makes the file write-protected via the QA-artifact hook (NOT filesystem
   permissions, FK-23 §23.4.3): once frozen, the ``ArtifactGuard`` blocks a
   sub-agent write to it. The freeze trigger feeds the guard-context signals
   ``change_frame_frozen`` / ``change_frame_freeze_known`` (see
   :meth:`DesignFreezeMarker.guard_context_signals`).

Bloodgroup-A purity (ARCH-22 / ARCH-31): the exploration core performs NO direct
filesystem I/O and never calls ``datetime.now`` itself. The frozen successor is
built immutably via ``model_copy`` (``ChangeFrame`` is ``frozen=True``); the file
write goes through the injected :class:`~agentkit.backend.exploration.ports.ChangeFrameWriter`
boundary port; ``frozen_at`` comes from an injected clock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from agentkit.backend.exploration.change_frame import ChangeFrame
    from agentkit.backend.exploration.ports import ChangeFrameWriter


class DesignFreezeMarker:
    """Freeze a change-frame after the exit-gate passes (FK-23 §23.4.3)."""

    def __init__(
        self,
        writer: ChangeFrameWriter,
        clock: Callable[[], datetime],
    ) -> None:
        """Initialise the freeze marker.

        Args:
            writer: The boundary port that re-materializes the protected
                ``change_frame.json`` file (the bloodgroup-A core does no I/O
                itself; the concrete state-backend adapter is wired at the
                composition-root).
            clock: A zero-arg callable returning the current tz-aware UTC
                timestamp for ``frozen_at`` (injected so the core never calls
                ``datetime.now`` directly; wired to ``lambda: datetime.now(UTC)``).
        """
        self._writer = writer
        self._clock = clock

    def freeze(
        self,
        change_frame: ChangeFrame,
        story_dir: Path,
        *,
        story_id: str,
        run_id: str,
    ) -> ChangeFrame:
        """Freeze the change-frame and re-write the protected file (FK-23 §23.4.3).

        Builds an immutable frozen successor (``frozen=True``, ``frozen_at`` from
        the injected clock) via ``model_copy`` and re-materializes the protected
        ``_temp/qa/{story_id}/change_frame.json`` through the injected writer. The
        write goes through the boundary FS port; the bloodgroup-A core stays
        I/O-free.

        Args:
            change_frame: The validated, gate-passed change-frame (still editable
                / not yet frozen).
            story_dir: The story working directory (resolves the protected path).
            story_id: The story display id (the ``_temp/qa/{story_id}/`` segment).
            run_id: The run correlation id the frame must belong to.

        Returns:
            The frozen successor :class:`ChangeFrame` (``frozen=True``,
            ``frozen_at`` set).
        """
        frozen_frame = change_frame.model_copy(
            update={"frozen": True, "frozen_at": self._clock()}
        )
        self._writer.write_change_frame_file(
            story_dir, story_id=story_id, run_id=run_id, frame=frozen_frame
        )
        return frozen_frame

    @staticmethod
    def guard_context_signals(frozen_frame: ChangeFrame) -> dict[str, object]:
        """Build the guard-context freeze signals from a persisted frozen frame.

        FK-23 §23.4.3 / AG3-045 AC8: after the freeze, the ``ArtifactGuard``
        blocks sub-agent writes to the change-frame iff the guard context carries
        ``change_frame_frozen=True``. The freeze trigger (this BC) feeds those
        signals from the AUTHORITATIVE persisted frozen frame -- never a guessed
        flag. ``change_frame_freeze_known`` records that the freeze state could be
        determined at all (a missing signal is fail-closed in the guard).

        Args:
            frozen_frame: The frozen change-frame (the persisted authoritative
                source of ``frozen``).

        Returns:
            A mapping with ``change_frame_frozen`` (the frame's ``frozen`` flag)
            and ``change_frame_freeze_known=True``, ready to merge into the guard
            evaluation context.
        """
        return {
            "change_frame_frozen": frozen_frame.frozen,
            "change_frame_freeze_known": True,
        }


__all__ = ["DesignFreezeMarker"]
