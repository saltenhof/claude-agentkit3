"""ExplorationDrafting -- worker-driven FK-23 change-frame production (BC 5).

The bloodgroup-A core of the ``exploration-and-design`` BC's ``ExplorationDrafting``
sub. It orchestrates the FK-23 §23.3 drafting WITHOUT doing any LLM / spawn / FS
I/O itself:

1. resolve + validate the worker spawn inputs (``StoryContext`` + run id) -- a
   missing context fails closed (no worker is run against an unknown story);
2. run the exploration worker through the :class:`ExplorationWorkerRunner` port
   (the LLM/worker boundary): the worker executes the seven FK-23 §23.3.2 steps
   and emits a seven-part change-frame payload. An EMPTY result (no draft) fails
   closed -- no artifact, clear rejection (no pseudo-/partial draft);
3. validate the raw payload into a typed :class:`ChangeFrame`
   (:meth:`ChangeFrame.from_payload`, fail-closed) and cross-check its inner
   identity against the requested (story, run) scope -- a frame stamped with a
   foreign id / run is rejected, not patched;
4. persist it BOTH as the protected ``_temp/qa/{story_id}/change_frame.json``
   file (via the AG3-045 :class:`~agentkit.backend.exploration.ports.ChangeFrameWriter`
   port) AND as the ``ArtifactClass.ENTWURF`` envelope (via the
   :class:`ChangeFrameSink` port). The file is written FIRST and the envelope
   second; an envelope-write failure rolls the file back, so the AG3-045 consumer
   (which reads the ENVELOPE) never observes an envelope whose protected file is
   missing (WARNING-1 atomicity; no partial-success state). This closes the
   produce->consume loop the handler's reader consumes.

Every failure edge is fail-closed: a missing input, an empty result, a
schema-invalid payload or a scope-mismatched frame leaves NO artifact behind and
raises a :class:`DraftingError` (or the underlying validation error). The content
is DERIVED by the worker from the story context / reference documents -- never a
static story constant, a ``conformant=True`` default, or rule-based fabrication
(Option Y, PO 2026-06-05).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.exploration.change_frame import ChangeFrame

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.artifacts.reference import ArtifactReference
    from agentkit.backend.exploration.drafting.persistence import ChangeFrameSink
    from agentkit.backend.exploration.drafting.ports import ExplorationWorkerRunner
    from agentkit.backend.exploration.ports import ChangeFrameWriter
    from agentkit.backend.story_context_manager.models import StoryContext


class DraftingError(RuntimeError):
    """Fail-closed rejection from the exploration drafting flow (ZERO DEBT).

    Raised when the worker produced no draft, or an input precondition is
    violated, so the caller never mistakes a missing/empty draft for a produced
    one. A schema-invalid payload surfaces the underlying ``ValidationError`` /
    ``TypeError`` from :meth:`ChangeFrame.from_payload` unchanged.
    """


@dataclass(frozen=True)
class ExplorationDraftRequest:
    """The inputs for one exploration drafting run.

    Attributes:
        ctx: The authoritative story context for the run (the worker spawn /
            prompt-materialization source). ``None`` fails closed.
        story_dir: The story working directory (resolves the protected
            ``_temp/qa/{story_id}/`` path for the change-frame file).
        run_id: The bound run correlation id (FK-02 §2.3.1 UUID).
        invocation_id: The spawn/invocation id (prompt-audit correlation).
        attempt: 1-based draft attempt counter (envelope ``attempt``).
    """

    ctx: StoryContext | None
    story_dir: Path
    run_id: str
    invocation_id: str
    attempt: int = 1


@dataclass(frozen=True)
class ExplorationDraftResult:
    """The outcome of a successful exploration drafting run.

    Attributes:
        change_frame: The validated, persisted worker-produced change-frame.
        envelope_reference: The reference of the persisted ENTWURF envelope.
        change_frame_path: The path of the materialized
            ``_temp/qa/{story_id}/change_frame.json`` (the AG3-045 read path).
        prompt_path: The POSIX path of the materialized ``worker-exploration.md``
            prompt instance the worker consumed (FK-44 audit trail).
    """

    change_frame: ChangeFrame
    envelope_reference: ArtifactReference
    change_frame_path: Path
    prompt_path: str


class ExplorationDrafting:
    """Produce + persist the FK-23 change-frame via the spawned worker (AG3-055).

    The bloodgroup-A orchestration: it drives the worker through the injected
    :class:`ExplorationWorkerRunner` port and persists the result through the
    :class:`ChangeFrameSink` (ENTWURF envelope) and the AG3-045
    :class:`ChangeFrameWriter` (protected change-frame file) ports. No LLM /
    spawn / FS I/O happens in this core (ARCH-22 / ARCH-31).
    """

    def __init__(
        self,
        worker_runner: ExplorationWorkerRunner,
        change_frame_sink: ChangeFrameSink,
        change_frame_writer: ChangeFrameWriter,
    ) -> None:
        """Initialize the drafting core with its three boundary ports.

        Args:
            worker_runner: The LLM/worker boundary port (productive spawn adapter
                or record-replay test adapter).
            change_frame_sink: The ENTWURF-envelope persistence port (FK-71).
            change_frame_writer: The AG3-045 boundary FS port that materializes
                the protected ``_temp/qa/{story_id}/change_frame.json`` file.
        """
        self._worker_runner = worker_runner
        self._sink = change_frame_sink
        self._writer = change_frame_writer

    def draft(self, request: ExplorationDraftRequest) -> ExplorationDraftResult:
        """Run the worker, validate its output, and persist the change-frame.

        Args:
            request: The drafting inputs (context + scope).

        Returns:
            An :class:`ExplorationDraftResult` with the persisted change-frame,
            its envelope reference and the materialized file path.

        Raises:
            DraftingError: When the story context is missing or the worker
                produced no draft (fail-closed; no artifact written).
            TypeError: When the worker payload is not a JSON object (from
                :meth:`ChangeFrame.from_payload`).
            pydantic.ValidationError: When the worker payload violates the
                change-frame schema (fail-closed; the draft is rejected, never
                patched).
        """
        ctx = request.ctx
        if ctx is None:
            raise DraftingError(
                "Exploration drafting requires a StoryContext; a worker is never "
                "run against an unknown story (FK-23 §23.3 / FAIL-CLOSED)."
            )

        result = self._worker_runner.run_exploration_worker(
            ctx, run_id=request.run_id, invocation_id=request.invocation_id
        )
        if result.payload is None:
            raise DraftingError(
                "Exploration worker produced no change-frame draft (empty "
                "result); refusing fail-closed -- no pseudo-/partial draft, no "
                f"fake APPROVED (FK-23 §23.3, story_id={ctx.story_id!r})."
            )

        # Fail-closed schema validation: the worker -- not the engine -- owns the
        # content; an invalid draft is rejected, never patched (Option Y).
        change_frame = ChangeFrame.from_payload(result.payload)
        self._reject_foreign_identity(change_frame, ctx, request.run_id)

        # Persist BOTH artifacts the worker produces (FK-23 §23.4.3 / AG3-045
        # AC7): the protected change_frame.json file AND the typed ENTWURF
        # envelope. WARNING-1 atomicity: the AG3-045 consumer reads the ENVELOPE
        # (``ChangeFrameReader.load_change_frame``) as the canonical truth; the
        # protected file is what the QA-guard protects and what the gate freezes.
        # Order so the consumer NEVER sees an envelope whose protected file is
        # missing: write the protected FILE FIRST, then the envelope. If the
        # envelope write fails, roll the file back so no half-success state
        # remains (no envelope without a file, no file without an envelope; ZERO
        # DEBT / FAIL-CLOSED). A later attempt overwrites the file atomically.
        change_frame_path = self._writer.write_change_frame_file(
            request.story_dir,
            story_id=ctx.story_id,
            run_id=request.run_id,
            frame=change_frame,
        )
        try:
            envelope_reference = self._sink.persist(
                change_frame, attempt=request.attempt
            )
        except Exception:
            # Roll the just-written protected file back: leaving it behind would
            # let a later handler read consume a frame whose ENTWURF envelope was
            # never materialized (a partial-success state). Best-effort unlink;
            # the original failure is re-raised unchanged (fail-closed).
            change_frame_path.unlink(missing_ok=True)
            raise
        return ExplorationDraftResult(
            change_frame=change_frame,
            envelope_reference=envelope_reference,
            change_frame_path=change_frame_path,
            prompt_path=result.prompt_path,
        )

    @staticmethod
    def _reject_foreign_identity(
        change_frame: ChangeFrame, ctx: StoryContext, run_id: str
    ) -> None:
        """Reject a worker draft whose inner identity is not the run scope.

        Mirrors the AG3-045 reader/writer identity cross-check: a change-frame
        stamped with a different ``story_id`` / ``run_id`` than the requested
        scope is refused fail-closed BEFORE any persistence (no artifact written).

        Args:
            change_frame: The validated change-frame.
            ctx: The story context for the run (scope source).
            run_id: The bound run correlation id.

        Raises:
            DraftingError: When the frame identity does not match the scope.
        """
        if change_frame.story_id != ctx.story_id or change_frame.run_id != run_id:
            raise DraftingError(
                "Exploration worker draft identity does not match the requested "
                "scope; refusing to persist a foreign inner frame "
                f"(requested story_id={ctx.story_id!r}, run_id={run_id!r}; "
                f"frame story_id={change_frame.story_id!r}, "
                f"run_id={change_frame.run_id!r})."
            )


__all__ = [
    "DraftingError",
    "ExplorationDraftRequest",
    "ExplorationDraftResult",
    "ExplorationDrafting",
]
