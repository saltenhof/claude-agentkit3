"""State-backend adapter exposing the exploration change-frame as BC-5 ports.

Option Y (PO decision 2026-06-05): the bloodgroup-A exploration domain core
(``agentkit.backend.exploration``) must not import ``state_backend.store`` nor touch the
filesystem directly (ARCH-22 / ARCH-31). This adapter satisfies the two
exploration boundary ports -- ``exploration.ports.RunScopeResolver`` and
``exploration.ports.ChangeFrameReader`` -- and is wired at the composition-root
(``bootstrap.composition_root.build_exploration_phase_handler``), mirroring
``StateBackendVerifyStoryContextAdapter`` (AG3-035).

* ``resolve_run_id`` delegates to ``load_flow_execution`` and fails
  closed (``CorruptStateError``) when no ``FlowExecution`` / ``run_id`` is bound.
* ``load_change_frame`` reads the latest persisted ENTWURF envelope via the
  injected :class:`ArtifactManager` (the only authorized artifact read surface)
  and validates its payload into a :class:`ChangeFrame` fail-closed. A missing
  envelope yields ``None`` (the AG3-055 worker has not produced one yet); a
  present-but-corrupt one raises (never a silent skip). The inner-frame identity
  is cross-checked against the requested scope (fail-closed CorruptStateError).
* ``write_change_frame_file`` materializes the change-frame as
  ``_temp/qa/{story_id}/change_frame.json`` atomically (temp file + ``os.replace``
  via :func:`agentkit.backend.utils.io.atomic_write_text`) -- the file the
  QA-artifact protection guards (FK-23 §23.4.3 / AG3-045 AC7). This is the
  authorized boundary FS write; the bloodgroup-A exploration core stays I/O-free.
  Before writing it cross-checks the frame's inner identity against the requested
  (story, run) scope (the write-path mirror of the reader's check) and refuses a
  foreign frame fail-closed (``CorruptStateError``) -- no file is written.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.backend.artifacts.errors import ArtifactNotFoundError
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.core_types.qa_artifact_names import (
    CHANGE_FRAME_DRAFT_FILE,
    CHANGE_FRAME_FILE,
)
from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.exploration.change_frame import ChangeFrame
from agentkit.backend.exploration.register import EXPLORATION_ENTWURF_STAGE
from agentkit.backend.installer.paths import resolve_qa_story_dir
from agentkit.backend.state_backend.pipeline_runtime_store import load_flow_execution
from agentkit.backend.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.artifacts import ArtifactManager


class StateBackendExplorationChangeFrameAdapter:
    """Adapter for the exploration ``RunScopeResolver`` / ``ChangeFrame`` ports.

    Satisfies ``RunScopeResolver``, ``ChangeFrameReader`` and ``ChangeFrameWriter``
    (the latter is the boundary FS port used by the change-frame PRODUCER --
    Option Y: the AG3-055 worker; in machinery tests its analogue).

    Args:
        artifact_manager: The authorized artifact read surface (DI). Used to
            read the latest ENTWURF envelope for a (story, run) scope.
    """

    def __init__(self, artifact_manager: ArtifactManager) -> None:
        self._artifact_manager = artifact_manager

    def resolve_run_id(self, story_dir: Path, *, story_id: str) -> str:
        """Resolve the run id bound to ``story_dir`` (fail-closed).

        Args:
            story_dir: The story working directory.
            story_id: The story display id (for the error detail).

        Returns:
            The non-empty run id of the bound ``FlowExecution``.

        Raises:
            CorruptStateError: When no ``FlowExecution`` / ``run_id`` is bound.
        """
        flow = load_flow_execution(story_dir)
        if flow is None or flow.run_id is None:
            raise CorruptStateError(
                "Exploration phase requires a bound FlowExecution with run_id; "
                "the pipeline_engine must persist it before drafting.",
                detail={"story_id": story_id, "story_dir": str(story_dir)},
            )
        return flow.run_id

    def load_change_frame(
        self, *, story_id: str, run_id: str
    ) -> ChangeFrame | None:
        """Load + validate the persisted change-frame for a (story, run).

        Args:
            story_id: The story display id.
            run_id: The run correlation id.

        Returns:
            The validated :class:`ChangeFrame`, or ``None`` when no ENTWURF
            envelope has been persisted for the scope yet.

        Raises:
            TypeError: When the persisted payload is not a JSON object.
            pydantic.ValidationError: When the persisted payload violates the
                change-frame schema (fail-closed; a corrupt frame is never
                silently skipped).
            CorruptStateError: When the inner change-frame's identity
                (``story_id`` / ``run_id``) does not match the requested scope
                (a foreign frame in this scope's envelope; fail-closed).
        """
        try:
            envelope = self._artifact_manager.read_latest(
                story_id=story_id,
                run_id=run_id,
                artifact_class=ArtifactClass.ENTWURF,
                stage=EXPLORATION_ENTWURF_STAGE,
            )
        except ArtifactNotFoundError:
            return None
        frame = ChangeFrame.from_payload(envelope.payload)
        # Identity cross-check (fail-closed): the envelope is addressed by the
        # (story_id, run_id) scope, but the INNER change-frame carries its own
        # story_id / run_id. A corrupt envelope wrapping a foreign frame must
        # never be accepted as this scope's artifact (ZERO DEBT / FAIL-CLOSED).
        if frame.story_id != story_id or frame.run_id != run_id:
            raise CorruptStateError(
                "Persisted change-frame identity does not match the requested "
                "scope; refusing to accept a foreign inner frame.",
                detail={
                    "requested_story_id": story_id,
                    "requested_run_id": run_id,
                    "frame_story_id": frame.story_id,
                    "frame_run_id": frame.run_id,
                },
            )
        return frame

    def worker_draft_present(self, story_dir: Path, *, story_id: str) -> bool:
        """Whether the worker raw draft exists under ``_temp/qa/{story_id}/``.

        Satisfies ``exploration.ports.WorkerDraftPresenceReader``: a pure boundary
        presence read the bloodgroup-A handler uses to decide consume-vs-spawn. It
        does NOT parse / validate the draft (that is the drafting core's job via
        its worker-runner port); it only reports whether the file exists.

        Args:
            story_dir: The story working directory (resolves
                ``_temp/qa/{story_id}/``).
            story_id: The story display id.

        Returns:
            ``True`` when ``change_frame.draft.json`` exists, else ``False``.
        """
        qa_dir = resolve_qa_story_dir(story_dir, story_id=story_id)
        return (qa_dir / CHANGE_FRAME_DRAFT_FILE).is_file()

    def write_change_frame_file(
        self, story_dir: Path, *, story_id: str, run_id: str, frame: ChangeFrame
    ) -> Path:
        """Atomically materialize ``_temp/qa/{story_id}/change_frame.json``.

        Writes the change-frame JSON to the QA-protected path (FK-23 §23.4.3 /
        AG3-045 AC7) ADDITIONALLY to the ArtifactManager envelope. The write is
        atomic (temp file + ``os.replace`` via
        :func:`agentkit.backend.utils.io.atomic_write_text`); a crash never leaves a
        half-written file behind.

        Before writing, the frame's inner identity is cross-checked against the
        requested (story, run) write scope -- the write-path mirror of the
        :meth:`load_change_frame` read-path check. A frame carrying a foreign
        ``story_id`` / ``run_id`` must never be materialized under this scope's
        protected path; the write is refused fail-closed (ZERO DEBT / FAIL-CLOSED).

        Args:
            story_dir: The story working directory (resolves the project root
                and thereby ``_temp/qa/{story_id}/``).
            story_id: The story display id (the ``_temp/qa/{story_id}/`` segment).
            run_id: The run correlation id the frame must belong to.
            frame: The validated change-frame to materialize.

        Returns:
            The path of the written ``change_frame.json``.

        Raises:
            CorruptStateError: When ``frame.story_id`` / ``frame.run_id`` do not
                match the requested write scope (no file is written).
        """
        if frame.story_id != story_id or frame.run_id != run_id:
            raise CorruptStateError(
                "Refusing to write a change-frame whose identity does not match "
                "the requested write scope (foreign inner frame).",
                detail={
                    "requested_story_id": story_id,
                    "requested_run_id": run_id,
                    "frame_story_id": frame.story_id,
                    "frame_run_id": frame.run_id,
                },
            )
        qa_dir = resolve_qa_story_dir(story_dir, story_id=story_id)
        target = qa_dir / CHANGE_FRAME_FILE
        atomic_write_text(target, json.dumps(frame.model_dump(mode="json"), indent=2))
        return target


__all__ = ["StateBackendExplorationChangeFrameAdapter"]
