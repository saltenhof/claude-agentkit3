"""QA-cycle lifecycle: identities and transitions (FK-27 §27.2).

:class:`QaCycleLifecycle` owns the atomic QA-cycle identities (FK-27 §27.2.1)
and the two transitions that mutate them:

* :meth:`start_cycle` -- begin the first cycle (round 1, epoch 1, fresh
  ``qa_cycle_id``, computed ``evidence_fingerprint``).
* :meth:`advance_qa_cycle` -- begin the next cycle after a failed remediation
  round: ``round += 1``, ``epoch += 1``, fresh ``qa_cycle_id``, recomputed
  ``evidence_fingerprint``, and invalidation of the cycle-bound artefacts
  (FK-27 §27.2.3 -> :func:`invalidate_cycle_artifacts`).

BC-topology (W2, AG3-026 Re-Review): the durable owner of the four identity
fields is ``ImplementationPayload`` in the pipeline-engine BC. To avoid a
``pipeline_engine`` import inside ``verify_system``, the lifecycle reads and
returns the BC-boundary DTO :class:`PhaseEnvelopeView`; the calling phase
handler (pipeline-engine BC) persists the returned view into the payload via
its ``PhaseEnvelopeStore``. The lifecycle thus has no second state truth -- it
computes the next identity tuple and hands it back to the state owner.

Source:
  - FK-27 §27.2.1 -- identity fields (qa_cycle_id, qa_cycle_round,
    evidence_epoch, evidence_fingerprint)
  - FK-27 §27.2.2 -- state machine (idle -> awaiting_qa -> ... -> pass |
    awaiting_remediation -> escalated)
  - FK-27 §27.2.3 -- artifact invalidation at cycle start
  - AG3-041 §2.1.1 -- QaCycleLifecycle
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.verify_system.contract import PhaseEnvelopeView
from agentkit.verify_system.errors import VerifySystemError
from agentkit.verify_system.qa_cycle.fingerprint import (
    DEFAULT_DIFF_BASE,
    compute_evidence_fingerprint,
)
from agentkit.verify_system.qa_cycle.invalidation import (
    ArtifactInvalidationEvent,
    ArtifactInvalidationSink,
    NullArtifactInvalidationSink,
    invalidate_cycle_artifacts,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class QaCycleState:
    """Snapshot of the four QA-cycle identity fields (FK-27 §27.2.1).

    Immutable value object. ``evidence_epoch`` is a counter-free timestamp;
    ``round`` and ``epoch`` are monotonic integers (>= 1 once a cycle exists).

    Attributes:
        qa_cycle_id: 12-char lowercase hex UUID-fragment of the active cycle.
        round: Monotonic QA-cycle counter (>= 1).
        epoch: Monotonic evidence epoch (>= 1).
        evidence_epoch: UTC-aware timestamp of the last artefact mutation.
        evidence_fingerprint: SHA-256 hex digest of the relevant artefacts.
    """

    qa_cycle_id: str
    round: int
    epoch: int
    evidence_epoch: datetime
    evidence_fingerprint: str

    def to_view(self) -> PhaseEnvelopeView:
        """Project the state into a BC-boundary :class:`PhaseEnvelopeView`.

        Returns:
            A frozen view carrying the four identity fields for the phase
            handler to persist into ``ImplementationPayload``.
        """
        return PhaseEnvelopeView(
            qa_cycle_id=self.qa_cycle_id,
            qa_cycle_round=self.round,
            evidence_epoch=self.evidence_epoch,
            evidence_fingerprint=self.evidence_fingerprint,
        )


@dataclass(frozen=True)
class QaCycleLifecycle:
    """Manages QA-cycle identities and transitions (FK-27 §27.2).

    Stateless coordinator: each method takes the current cycle context as
    input and returns the next identity snapshot. State persistence is the
    caller's responsibility (the phase handler in the pipeline-engine BC),
    keeping a single state owner (FIX THE MODEL).

    Attributes:
        invalidation_sink: Sink receiving ``artifact_invalidated`` facts on
            :meth:`advance_qa_cycle`. Defaults to the no-op sink.
        diff_base: Git revision the fingerprint delta is taken against
            (default ``origin/main``, FK-27 §27.2.1).
    """

    invalidation_sink: ArtifactInvalidationSink = NullArtifactInvalidationSink()
    diff_base: str = DEFAULT_DIFF_BASE

    def start_cycle(self, story_dir: Path) -> QaCycleState:
        """Begin the first QA cycle for a story (FK-27 §27.2.1).

        Generates a fresh ``qa_cycle_id`` (UUID4 12-char fragment), sets
        ``round = 1`` and ``epoch = 1``, stamps ``evidence_epoch`` with the
        current UTC instant and computes ``evidence_fingerprint`` over the
        current code-state.

        Args:
            story_dir: Story working directory (git root + handover root).

        Returns:
            The initial :class:`QaCycleState` (round 1, epoch 1).
        """
        return QaCycleState(
            qa_cycle_id=_new_cycle_id(),
            round=1,
            epoch=1,
            evidence_epoch=_now_utc(),
            evidence_fingerprint=compute_evidence_fingerprint(
                story_dir, diff_base=self.diff_base
            ),
        )

    def advance_qa_cycle(
        self,
        current: PhaseEnvelopeView,
        story_dir: Path,
        story_id: str,
        *,
        project_root: Path | None = None,
    ) -> tuple[QaCycleState, tuple[ArtifactInvalidationEvent, ...]]:
        """Begin the next QA cycle after a failed remediation round.

        Increments ``round`` and ``epoch`` by one, generates a fresh
        ``qa_cycle_id``, re-stamps ``evidence_epoch``, recomputes
        ``evidence_fingerprint`` and invalidates the cycle-bound artefacts of
        the *previous* epoch (FK-27 §27.2.3): they are moved to
        ``stale/{old_epoch}/`` and an ``artifact_invalidated`` fact is emitted
        per moved file.

        Args:
            current: BC-boundary view of the active cycle identities. Must
                carry a set ``qa_cycle_id`` and ``qa_cycle_round >= 1``
                (a cycle must have been started first; fail-closed otherwise).
            story_dir: Story working directory.
            story_id: Story display-ID (artefact path segment, FK-27 §27.2.3).
            project_root: Optional project root forwarded to the canonical
                QA-artefact-dir resolver (AG3-041 E4 — single path truth).

        Returns:
            A ``(QaCycleState, invalidation_events)`` tuple: the next cycle's
            identities and the emitted invalidation facts.

        Raises:
            VerifySystemError: If ``current`` has no active cycle to advance
                from (no ``qa_cycle_id`` / ``qa_cycle_round``).
        """
        prev_round = current.qa_cycle_round
        if current.qa_cycle_id is None or prev_round is None or prev_round < 1:
            msg = (
                "advance_qa_cycle requires an active cycle (qa_cycle_id set "
                "and qa_cycle_round >= 1); call start_cycle first. Got "
                f"qa_cycle_id={current.qa_cycle_id!r}, "
                f"qa_cycle_round={current.qa_cycle_round!r}"
            )
            raise VerifySystemError(msg)

        old_epoch = _epoch_of(current, fallback=prev_round)

        # FK-27 §27.2.3: invalidate the previous epoch's cycle-bound artefacts
        # BEFORE the new identities take effect (no stale consumption).
        events = invalidate_cycle_artifacts(
            story_dir=story_dir,
            story_id=story_id,
            old_epoch=old_epoch,
            sink=self.invalidation_sink,
            project_root=project_root,
        )

        next_state = QaCycleState(
            qa_cycle_id=_new_cycle_id(),
            round=prev_round + 1,
            epoch=old_epoch + 1,
            evidence_epoch=_now_utc(),
            evidence_fingerprint=compute_evidence_fingerprint(
                story_dir, diff_base=self.diff_base
            ),
        )
        return next_state, events

    @staticmethod
    def get_current_state(current: PhaseEnvelopeView) -> QaCycleState | None:
        """Read the active cycle identities from a BC-boundary view.

        Args:
            current: BC-boundary view of the phase payload.

        Returns:
            A :class:`QaCycleState` when an active cycle exists (all four
            identity fields present), otherwise ``None`` (idle state).
        """
        if (
            current.qa_cycle_id is None
            or current.qa_cycle_round is None
            or current.evidence_epoch is None
            or current.evidence_fingerprint is None
        ):
            return None
        return QaCycleState(
            qa_cycle_id=current.qa_cycle_id,
            round=current.qa_cycle_round,
            epoch=_epoch_of(current, fallback=current.qa_cycle_round),
            evidence_epoch=current.evidence_epoch,
            evidence_fingerprint=current.evidence_fingerprint,
        )


def _epoch_of(view: PhaseEnvelopeView, *, fallback: int) -> int:
    """Resolve the evidence epoch for a view.

    ``PhaseEnvelopeView`` carries no dedicated epoch field (the durable model
    keeps ``evidence_epoch`` as a timestamp, FK-27 §27.2.1). For invalidation
    bookkeeping the epoch tracks the cycle round one-to-one (both start at 1
    and advance together), so the round is the authoritative epoch counter.

    Args:
        view: BC-boundary view.
        fallback: Round to use as the epoch (epoch == round invariant).

    Returns:
        The epoch integer (== round).
    """
    del view  # epoch is derived from the round (epoch == round, FK-27 §27.2).
    return fallback


def _new_cycle_id() -> str:
    """Generate a fresh 12-char lowercase hex QA-cycle id (FK-27 §27.2.1).

    Returns:
        The first 12 hex characters of a UUID4.
    """
    return uuid.uuid4().hex[:12]


def _now_utc() -> datetime:
    """Return the current UTC-aware instant for ``evidence_epoch``.

    Returns:
        A timezone-aware UTC datetime.
    """
    return datetime.now(tz=UTC)


__all__ = [
    "QaCycleLifecycle",
    "QaCycleState",
]
