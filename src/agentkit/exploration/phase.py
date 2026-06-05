"""ExplorationPhaseHandler -- entry point of the exploration phase (FK-23 §23.3).

The handler satisfies the engine's ``PhaseHandler`` protocol
(``pipeline_engine.lifecycle``). Per the PO decision 2026-06-05 ("Option Y") it
delivers the deterministic plumbing of the exploration phase, NOT the content
drafting: the real change-frame is produced by the spawned exploration worker
(AG3-055, BC ``agent-skills``). ``on_enter`` therefore CONSUMES / VALIDATES an
already-persisted change-frame -- it never fabricates one:

* a valid persisted change-frame exists -> validate it; the phase PAUSES
  awaiting the three-stage design review (AG3-046, ``AWAITING_DESIGN_REVIEW``).
  The gate stays ``PENDING``; only AG3-046's review transitions it to
  ``APPROVED`` (no fake-APPROVED here);
* no change-frame is persisted yet -> fail-closed ESCALATED rejection with a
  clear "exploration drafting requires AG3-055" message (no pseudo-draft).

The persistence / run correlation runs through injected boundary ports
(``ports.ChangeFrameReader`` / ``ports.RunScopeResolver``); the bloodgroup-A
domain core performs no direct filesystem I/O nor ``state_backend.store``
imports. The productive composition-root wiring (registering this handler on the
``PhaseHandlerRegistry``) is owned by AG3-054; this story delivers the
registrable handler and its self-registration surface
(``build_exploration_phase_handler``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.core_types import ExplorationGateStatus, PauseReason
from agentkit.pipeline_engine.lifecycle import HandlerResult
from agentkit.story_context_manager.models import (
    ExplorationPayload,
    PhaseName,
    PhaseState,
    PhaseStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.exploration.ports import ChangeFrameReader, RunScopeResolver
    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.story_context_manager.models import StoryContext

#: Fail-closed message stamped on the ESCALATED rejection when no worker-produced
#: change-frame is present (Option Y: drafting belongs to AG3-055).
_NO_CHANGE_FRAME_MESSAGE = (
    "Exploration drafting requires AG3-055: no valid change-frame has been "
    "persisted for this story/run. The exploration phase consumes a "
    "worker-produced change-frame (ArtifactClass.ENTWURF); it does not "
    "fabricate one. Escalating fail-closed (no pseudo-draft, no fake APPROVED)."
)


@dataclass(frozen=True)
class ExplorationConfig:
    """Configuration for the exploration phase handler.

    Attributes:
        story_dir: Story working directory (where the bound ``FlowExecution``
            lives). ``None`` fails closed in ``on_enter``.
    """

    story_dir: Path | None = None


class ExplorationPhaseHandler:
    """Run the exploration phase: validate the worker change-frame, drive gate."""

    def __init__(
        self,
        change_frame_reader: ChangeFrameReader,
        run_scope_resolver: RunScopeResolver,
        review: object | None = None,
        *,
        config: ExplorationConfig | None = None,
    ) -> None:
        """Initialize the handler.

        Args:
            change_frame_reader: Boundary port that reads / validates the
                persisted change-frame (DI; concrete adapter wired at the
                composition-root).
            run_scope_resolver: Boundary port that resolves the bound run id
                (DI).
            review: AG3-046 injection slot for the three-stage
                ``ExplorationReview``. Unused in AG3-045 (the phase pauses
                awaiting review); AG3-046 narrows the type and activates it.
            config: Handler configuration; defaults to an empty
                :class:`ExplorationConfig` (``story_dir=None`` fails closed).
        """
        self._reader = change_frame_reader
        self._run_scope = run_scope_resolver
        # AG3-046 replaces the "pause awaiting review" branch in ``on_enter``
        # with ``self._review.run(change_frame, ctx)`` (full ExplorationReview).
        self._review = review
        self._config = config or ExplorationConfig()

    def on_enter(self, ctx: StoryContext, envelope: PhaseEnvelope) -> HandlerResult:
        """Validate the persisted change-frame and resolve the exit-gate.

        Reads the worker-produced change-frame (AG3-055) via the boundary port:
        a valid frame pauses the phase awaiting design review (AG3-046); no
        frame escalates fail-closed.

        Args:
            ctx: The story context for this run.
            envelope: The current phase envelope (state + runtime).

        Returns:
            ``HandlerResult.PAUSED`` (``AWAITING_DESIGN_REVIEW``) with the gate
            still ``PENDING`` when a valid change-frame is present; ``ESCALATED``
            (fail-closed) when none is present or ``FAILED`` when the handler is
            not configured with a ``story_dir``.

        Raises:
            CorruptStateError: When no bound ``FlowExecution`` with a ``run_id``
                exists (fail-closed; setup must persist it before exploration).
        """
        state = envelope.state
        story_dir = self._config.story_dir
        if story_dir is None:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=("story_dir is not configured in ExplorationConfig",),
                updated_state=self._exploration_state(
                    state, PhaseStatus.FAILED, ExplorationGateStatus.PENDING
                ),
            )

        run_id = self._run_scope.resolve_run_id(story_dir, story_id=ctx.story_id)
        change_frame = self._reader.load_change_frame(
            story_id=ctx.story_id, run_id=run_id
        )
        if change_frame is None:
            # Fail-closed: no worker-produced change-frame -> escalate. No
            # pseudo-draft, no fake APPROVED (Option Y; FK-23 §23.3).
            return HandlerResult(
                status=PhaseStatus.ESCALATED,
                errors=(_NO_CHANGE_FRAME_MESSAGE,),
                updated_state=self._exploration_state(
                    state, PhaseStatus.ESCALATED, ExplorationGateStatus.PENDING
                ),
            )

        # A valid change-frame is present (the reader validated it fail-closed).
        # The exit-gate is owned by the three-stage ExplorationReview (AG3-046);
        # until then the phase PAUSES with the gate still PENDING -- never an
        # APPROVED set here (FK-23 §23.5 / §23.6.1).
        return HandlerResult(
            status=PhaseStatus.PAUSED,
            yield_status=PauseReason.AWAITING_DESIGN_REVIEW.value,
            updated_state=self._exploration_state(
                state, PhaseStatus.PAUSED, ExplorationGateStatus.PENDING
            ),
        )

    def on_exit(self, _ctx: StoryContext, _envelope: PhaseEnvelope) -> None:
        """No-op for the exploration phase (no snapshot side effects here)."""

    def on_resume(
        self, ctx: StoryContext, envelope: PhaseEnvelope, trigger: str,
    ) -> HandlerResult:
        """Resume the exploration phase.

        AG3-045 owns no review logic (AG3-046 owns the gate transitions);
        resuming re-runs ``on_enter``, which re-validates the persisted
        change-frame idempotently.

        Args:
            ctx: The story context for this run.
            envelope: The current phase envelope.
            trigger: The resume trigger (unused in AG3-045).

        Returns:
            The :class:`HandlerResult` from ``on_enter``.
        """
        del trigger
        return self.on_enter(ctx, envelope)

    @staticmethod
    def _exploration_state(
        state: PhaseState,
        status: PhaseStatus,
        gate_status: ExplorationGateStatus,
    ) -> PhaseState:
        """Rebuild the exploration ``PhaseState`` with the given gate status.

        Args:
            state: The incoming phase state (memory / attempt id preserved).
            status: The phase status to set.
            gate_status: The exploration gate status to persist in the payload.

        Returns:
            A new ``PhaseState`` for the exploration phase.
        """
        return PhaseState(
            story_id=state.story_id,
            phase=PhaseName.EXPLORATION,
            status=status,
            payload=ExplorationPayload(gate_status=gate_status),
            memory=state.memory,
            paused_reason=state.paused_reason,
            review_round=state.review_round,
            errors=list(state.errors),
            attempt_id=state.attempt_id,
        )


__all__ = ["ExplorationConfig", "ExplorationPhaseHandler"]
