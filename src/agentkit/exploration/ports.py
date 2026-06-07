"""Boundary ports for the exploration phase handler (BC 5, bloodgroup A).

``agentkit.exploration`` is a bloodgroup-A domain core
(``architecture-conformance.group.exploration``). Per ARCH-22 / ARCH-31 it MUST
NOT perform direct filesystem I/O (``mkdir`` / ``write_text``) nor import
``agentkit.state_backend.store`` directly. The persisted change-frame and the
run correlation are resolved through these injected ports; the concrete
state-backend adapters live OUTSIDE this BC and are wired at the
composition-root (``bootstrap.composition_root.build_exploration_phase_handler``),
mirroring ``verify_system.protocols.StoryContextQueryPort`` /
``StateBackendVerifyStoryContextAdapter`` (AG3-035).

Fail-closed semantics (FK-23 §23.3 / §23.4.3, ZERO DEBT):

* :class:`ChangeFrameReader.load_change_frame` returns ``None`` when no
  change-frame has been persisted yet (the AG3-055 worker has not produced one)
  and raises on a corrupt / unreadable persisted frame. The handler turns the
  ``None`` into a clear, fail-closed rejection.
* :class:`RunScopeResolver.resolve_run_id` returns the bound run id or raises
  ``CorruptStateError`` when no ``FlowExecution`` / ``run_id`` is bound -- the
  pipeline engine must persist it before the exploration phase runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.exploration.change_frame import ChangeFrame
    from agentkit.story_context_manager.story_model import ChangeImpact


@runtime_checkable
class RunScopeResolver(Protocol):
    """Resolve the run id bound to a story directory (fail-closed)."""

    def resolve_run_id(self, story_dir: Path, *, story_id: str) -> str:
        """Return the non-empty run id bound to ``story_dir``.

        Args:
            story_dir: The story working directory.
            story_id: The story display id (for the error detail).

        Returns:
            The non-empty run id of the bound ``FlowExecution``.

        Raises:
            CorruptStateError: When no ``FlowExecution`` / ``run_id`` is bound
                (fail-closed; setup must persist it before exploration).
        """
        ...


@runtime_checkable
class ChangeFrameReader(Protocol):
    """Read and validate the persisted exploration change-frame (fail-closed)."""

    def load_change_frame(
        self, *, story_id: str, run_id: str
    ) -> ChangeFrame | None:
        """Load the persisted, validated change-frame for a (story, run).

        Args:
            story_id: The story display id.
            run_id: The run correlation id.

        Returns:
            The validated :class:`ChangeFrame`, or ``None`` when no change-frame
            has been persisted for the (story, run) scope yet (the AG3-055
            worker has not produced one).

        Raises:
            Exception: When a change-frame IS present but is corrupt / fails
                schema validation (fail-closed; never a silent skip).
        """
        ...


@runtime_checkable
class ChangeFrameWriter(Protocol):
    """Materialize the change-frame FILE on disk via the boundary FS port.

    FK-23 §23.4.3 / AG3-045 AC7: in ADDITION to the ArtifactManager envelope,
    the change-frame is materialized as ``_temp/qa/{story_id}/change_frame.json``
    -- the very path the QA-artifact protection (``ArtifactGuard`` /
    ``PROTECTED_CHANGE_FRAME``) guards. The file is written by the producing
    actor (Option Y: the AG3-055 worker; in machinery tests the worker analogue
    ``persist_example_change_frame``), NOT by the consuming phase handler.
    The bloodgroup-A exploration core never performs this I/O itself; the
    concrete adapter does (``state_backend.store`` / ARCH-22 / ARCH-31).
    """

    def write_change_frame_file(
        self, story_dir: Path, *, story_id: str, run_id: str, frame: ChangeFrame
    ) -> Path:
        """Atomically write ``change_frame.json`` for the story (temp + replace).

        The writer cross-checks the frame's inner identity against the requested
        (story, run) scope BEFORE writing: a frame stamped with a different
        ``story_id`` / ``run_id`` than the write scope is refused fail-closed
        (it must never be materialized under a foreign scope's protected path).

        Args:
            story_dir: The story working directory (used to resolve the project
                root and thereby ``_temp/qa/{story_id}/``).
            story_id: The story display id (the ``_temp/qa/{story_id}/`` segment).
            run_id: The run correlation id the frame must belong to.
            frame: The validated change-frame to materialize.

        Returns:
            The path of the written ``change_frame.json``.

        Raises:
            CorruptStateError: When ``frame.story_id`` / ``frame.run_id`` do not
                match the requested write scope (fail-closed).
        """
        ...


@runtime_checkable
class DeclaredImpactReader(Protocol):
    """Resolve the authoritative DECLARED change impact of a story (fail-closed).

    FK-25 §25.7.1 (Klasse 4) compares the change-frame's actual impact against
    the story's DECLARED ``change_impact``. That value lives on the
    :class:`~agentkit.story_context_manager.story_model.Story` model (the GitHub
    input / story stammdaten) -- NOT on ``StoryContext`` (runtime model) nor on
    the 2-value ``ImplementationContract``. The bloodgroup-A exploration core
    must not read the story store directly (ARCH-22 / ARCH-31); it resolves the
    declared impact through this injected boundary port, whose concrete adapter
    (state-backend ``StoryRepository`` read) is wired at the composition-root.

    Fail-closed (FIX-THE-MODEL, no second source of truth, no fail-open default,
    FK-25 §25.7.1): when the declared impact cannot be resolved (no such story /
    unreadable store) the implementation RAISES rather than defaulting to
    ``LOCAL`` -- absence is an error, never a silent autonomous pass.
    """

    def declared_change_impact(self, *, story_id: str) -> ChangeImpact:
        """Return the story's declared change impact (fail-closed).

        Args:
            story_id: The story display id.

        Returns:
            The authoritative declared :class:`ChangeImpact` from the story
            stammdaten.

        Raises:
            Exception: When the story / its declared impact cannot be resolved
                (fail-closed; never a silent ``LOCAL`` default).
        """
        ...


__all__ = [
    "ChangeFrameReader",
    "ChangeFrameWriter",
    "DeclaredImpactReader",
    "RunScopeResolver",
]
