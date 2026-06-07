"""ExplorationPhaseHandler -- entry point of the exploration phase (FK-23 §23.3).

The handler satisfies the engine's ``PhaseHandler`` protocol
(``pipeline_engine.lifecycle``). Per the PO decision 2026-06-05 ("Option Y") it
delivers the deterministic plumbing of the exploration phase, NOT the content
drafting: the real change-frame is produced by the spawned exploration worker
(AG3-055, BC ``agent-skills``). ``on_enter`` therefore CONSUMES / VALIDATES an
already-persisted change-frame -- it never fabricates one:

* a valid persisted change-frame exists -> validate it, then run the three-stage
  exit-gate (AG3-046, :class:`~agentkit.exploration.review.ExplorationReview`).
  The gate decides ``ExplorationPayload.gate_status``:

  - ``APPROVED`` (all stages passed) -> ``COMPLETED`` (implementation released);
  - Stage-2a round-limit escalation -> ``ESCALATED``, gate stays ``PENDING``,
    the story STAYS in the exploration phase (operator intervention; FK-23
    §23.5.2 / FK-45 §45.3);
  - ``REJECTED`` (Stage-1 FAIL or a non-escalated Stage-2a/2b FAIL) ->
    ``ESCALATED``, gate ``REJECTED`` (architecture conflict; FK-23 §23.5 /
    FK-45 §45.3). There is NO path to ``APPROVED`` without a Stage-1 PASS
    (NO ERROR BYPASSING);
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
    from agentkit.exploration.review import ExplorationGateResult, ExplorationReview
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

#: Fail-closed message when the handler has no ExplorationReview wired but a
#: valid change-frame is present (the gate cannot be run -> never auto-APPROVE).
_NO_REVIEW_MESSAGE = (
    "Exploration exit-gate cannot run: no ExplorationReview is wired into the "
    "handler. Refusing to release the gate fail-closed (no path to APPROVED "
    "without the three-stage review, FK-23 §23.5 / NO ERROR BYPASSING)."
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
        review: ExplorationReview | None = None,
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
            review: The three-stage exploration exit-gate
                (:class:`~agentkit.exploration.review.ExplorationReview`,
                AG3-046). When a valid change-frame is present, ``on_enter`` runs
                this gate and maps its result onto ``gate_status``. ``None``
                fails closed (the gate cannot be released without the review).
            config: Handler configuration; defaults to an empty
                :class:`ExplorationConfig` (``story_dir=None`` fails closed).
        """
        self._reader = change_frame_reader
        self._run_scope = run_scope_resolver
        self._review = review
        self._config = config or ExplorationConfig()

    def on_enter(self, ctx: StoryContext, envelope: PhaseEnvelope) -> HandlerResult:
        """Validate the persisted change-frame and run the three-stage exit-gate.

        Reads the worker-produced change-frame (AG3-055) via the boundary port; a
        valid frame is driven through the :class:`ExplorationReview` exit-gate
        (AG3-046) and the gate result is mapped onto the phase result; no frame
        escalates fail-closed.

        Args:
            ctx: The story context for this run.
            envelope: The current phase envelope (state + runtime).

        Returns:
            ``COMPLETED`` (gate ``APPROVED``) when all gate stages passed;
            ``ESCALATED`` when Stage 2a hit the round limit (gate ``PENDING``,
            story stays in exploration) or the gate ``REJECTED`` (gate
            ``REJECTED``); ``ESCALATED`` (fail-closed) when no change-frame is
            present; ``FAILED`` when not configured with a ``story_dir`` or when
            no review is wired.

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

        if self._review is None:
            # Fail-closed: a valid frame but no gate wired -> never auto-APPROVE.
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=(_NO_REVIEW_MESSAGE,),
                updated_state=self._exploration_state(
                    state, PhaseStatus.FAILED, ExplorationGateStatus.PENDING
                ),
            )

        # A valid change-frame is present (the reader validated it fail-closed).
        # Run the three-stage exit-gate (Stage 1 -> Stage 2a -> opt. Stage 2b)
        # and map the gate decision onto the phase result (FK-23 §23.5).
        gate_result = self._review.run(change_frame)
        return self._map_gate_result(state, gate_result)

    def _map_gate_result(
        self, state: PhaseState, gate_result: ExplorationGateResult
    ) -> HandlerResult:
        """Map an :class:`ExplorationGateResult` onto a :class:`HandlerResult`.

        Args:
            state: The incoming phase state (memory / attempt id preserved).
            gate_result: The three-stage gate outcome.

        Returns:
            ``COMPLETED`` for ``APPROVED``; ``ESCALATED`` for a Stage-2a
            round-limit escalation (gate ``PENDING``, story stays in exploration)
            and for a ``REJECTED`` gate (gate ``REJECTED``).
        """
        if gate_result.overall_status is ExplorationGateStatus.APPROVED:
            return HandlerResult(
                status=PhaseStatus.COMPLETED,
                updated_state=self._exploration_state(
                    state, PhaseStatus.COMPLETED, ExplorationGateStatus.APPROVED
                ),
            )
        if gate_result.is_escalated:
            # FK-23 §23.5.2 round-limit: ESCALATED, gate stays PENDING, story
            # STAYS in the exploration phase (no transition to implementation).
            return HandlerResult(
                status=PhaseStatus.ESCALATED,
                yield_status=PauseReason.AWAITING_DESIGN_REVIEW.value,
                errors=(gate_result.escalation_reason,)
                if gate_result.escalation_reason
                else (),
                suggested_reaction=gate_result.escalation_reason,
                updated_state=self._exploration_state(
                    state, PhaseStatus.ESCALATED, ExplorationGateStatus.PENDING
                ),
            )
        # REJECTED (Stage-1 FAIL or a non-escalated Stage-2a/2b FAIL): hard
        # architecture conflict -> ESCALATED with gate REJECTED (FK-45 §45.3
        # doc_fidelity_fail / design_review_rejected). The Implementation guard
        # (exploration_gate_approved) denies a REJECTED gate.
        return HandlerResult(
            status=PhaseStatus.ESCALATED,
            errors=(_rejection_reason(gate_result),),
            updated_state=self._exploration_state(
                state, PhaseStatus.ESCALATED, ExplorationGateStatus.REJECTED
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


def _rejection_reason(gate_result: ExplorationGateResult) -> str:
    """Build the operator-facing reason for a REJECTED gate (FK-45 §45.3).

    Args:
        gate_result: The REJECTED gate outcome.

    Returns:
        A concise reason: ``doc_fidelity_fail`` when Stage 1 failed, else
        ``design_review_rejected`` (Stage 2a/2b FAIL).
    """
    if gate_result.stage1_result.status != "pass":
        return (
            "Exploration exit-gate REJECTED: Stage 1 document-fidelity FAILED "
            "(doc_fidelity_fail, FK-23 §23.5.1). Architecture conflict -- "
            "operator must resolve before implementation."
        )
    return (
        "Exploration exit-gate REJECTED: design review/challenge FAILED "
        "(design_review_rejected, FK-23 §23.5). Operator intervention required."
    )


__all__ = ["ExplorationConfig", "ExplorationPhaseHandler"]
