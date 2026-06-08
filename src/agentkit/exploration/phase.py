"""Exploration phase handler: consume worker change-frames, gate, or spawn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.core_types import (
    ExplorationGateStatus,
    PauseReason,
    SpawnKind,
    SpawnReason,
    SpawnRequest,
)
from agentkit.pipeline_engine.lifecycle import HandlerResult
from agentkit.story_context_manager.models import (
    ExplorationPayload,
    PhaseName,
    PhaseState,
    PhaseStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.exploration.change_frame import ChangeFrame
    from agentkit.exploration.drafting.drafting import ExplorationDrafting
    from agentkit.exploration.freeze import DesignFreezeMarker
    from agentkit.exploration.mandate.classification import MandateClassification
    from agentkit.exploration.mandate.fine_design import (
        FineDesignResult,
        FineDesignSubprocess,
    )
    from agentkit.exploration.mandate.telemetry import MandateTelemetry
    from agentkit.exploration.ports import (
        ChangeFrameReader,
        DeclaredImpactReader,
        RunScopeResolver,
        WorkerDraftPresenceReader,
    )
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

#: Fail-closed message when mandate classification is wired but its declared-
#: impact port is not (the Klasse-4 check cannot run -> never silent autonomous).
_NO_IMPACT_READER_MESSAGE = (
    "Mandate classification cannot run: no DeclaredImpactReader is wired into "
    "the handler. The Klasse-4 impact-exceedance check requires the story's "
    "declared change_impact; refusing fail-closed (no LOCAL default, FK-25 "
    "§25.7.1 / FIX-THE-MODEL)."
)

#: Operator-facing escalation reaction for a Klasse-3 scope explosion (no auto
#: story split: StorySplitService is out of scope, FK-25 §25.6.3).
_SCOPE_EXPLOSION_REACTION = "scope_explosion_detected: recommend story split"

#: Operator-facing escalation reaction for a Klasse-4 impact escalation.
_IMPACT_ESCALATION_REACTION = "impact_exceedance: architecture review needed"

#: Operator-facing escalation reaction when the fine-design subprocess did not
#: converge within the round limit (FK-25 §25.5.1).
_FINE_DESIGN_MAX_ROUNDS_REACTION = (
    "fine_design_max_rounds_exceeded: fine-design subprocess did not converge "
    "within the round limit -- operator decision required (FK-25 §25.5.1)"
)

#: Operator-facing escalation reaction when the fine-design evaluator could not
#: run at all (FK-25 §25.5.4 non-reachability). The productive wiring escalates
#: a fine-design (Klasse-2) story here until the real multi-LLM evaluator exists
#: (follow-up story); it never silently converges a class-2 frame.
_FINE_DESIGN_UNAVAILABLE_REACTION = (
    "fine_design_required: real fine-design evaluator not yet available "
    "(follow-up); operator intervention required (FK-25 §25.5 / §25.5.4)"
)


@dataclass(frozen=True)
class _DraftingLoopResult:
    """Outcome of the no-change-frame produce->consume loop (AG3-055).

    Either a terminal :class:`HandlerResult` (a spawn-and-await ``IN_PROGRESS``,
    a fail-closed escalation, or a drafting failure) OR -- when ``terminal`` is
    ``None`` -- the freshly consumed-and-re-read :class:`ChangeFrame` to continue
    into the mandate flow + exit-gate.

    Attributes:
        terminal: A terminal handler result, or ``None`` to continue with
            ``change_frame``.
        change_frame: The re-read change-frame (only meaningful when ``terminal``
            is ``None``).
    """

    terminal: HandlerResult | None = None
    change_frame: ChangeFrame | None = None


@dataclass(frozen=True)
class _MandateRouting:
    """Internal carrier for the mandate-routing decision (AG3-047).

    Either a terminal :class:`HandlerResult` (an escalating class, a missing
    collaborator, or a non-converged fine-design) OR -- when ``terminal`` is
    ``None`` -- the ``run_design_challenge`` flag for the surviving classes that
    flow into the exit-gate.

    Attributes:
        terminal: A terminal handler result, or ``None`` to continue to the gate.
        run_design_challenge: The Stage-2b mandate-gating flag (only meaningful
            when ``terminal`` is ``None``).
    """

    terminal: HandlerResult | None = None
    run_design_challenge: bool = True


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
        mandate_classification: MandateClassification | None = None,
        declared_impact_reader: DeclaredImpactReader | None = None,
        fine_design: FineDesignSubprocess | None = None,
        freeze_marker: DesignFreezeMarker | None = None,
        telemetry: MandateTelemetry | None = None,
        drafting: ExplorationDrafting | None = None,
        draft_presence: WorkerDraftPresenceReader | None = None,
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
            mandate_classification: The mandate classifier (AG3-047, FK-25
                §25.4.1). When wired, ``on_enter`` classifies the change-frame
                BEFORE the review and routes the escalating classes fail-closed.
                ``None`` preserves the AG3-046 behaviour (straight to review).
            declared_impact_reader: Boundary port resolving the story's declared
                change impact for the Klasse-4 check (AG3-047, FK-25 §25.7.1).
                Required when ``mandate_classification`` is wired; its absence
                then fails closed (no LOCAL default).
            fine_design: The Klasse-2 fine-design subprocess skeleton (AG3-047,
                FK-25 §25.5). Required when ``mandate_classification`` is wired
                (the fine-design class routes through it).
            freeze_marker: The design-freeze marker (AG3-047, FK-23 §23.4.3).
                When wired, an APPROVED gate freezes the change-frame before
                COMPLETED. ``None`` preserves the AG3-046 behaviour (no freeze).
            telemetry: The mandate telemetry emitter (AG3-047, FK-25 §25.8).
                Required when ``mandate_classification`` is wired (the four
                events are emitted at their routing points).
            drafting: The AG3-055 :class:`ExplorationDrafting` core (the
                consume/validate/persist A-core). When wired together with
                ``draft_presence``, ``on_enter`` drives the produce->consume loop:
                a present worker draft is CONSUMED here; no draft EMITS a typed
                spawn order. ``None`` (with ``draft_presence`` ``None``) keeps the
                legacy fail-closed ESCALATED branch.
            draft_presence: The :class:`WorkerDraftPresenceReader` boundary port
                reporting whether the worker wrote its raw draft. Required to
                drive the produce->consume loop; ``None`` keeps the legacy branch.
        """
        self._reader = change_frame_reader
        self._run_scope = run_scope_resolver
        self._review = review
        self._config = config or ExplorationConfig()
        self._mandate = mandate_classification
        self._declared_impact_reader = declared_impact_reader
        self._fine_design = fine_design
        self._freeze_marker = freeze_marker
        self._telemetry = telemetry
        self._drafting = drafting
        self._draft_presence = draft_presence

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
            ``REJECTED``); ``IN_PROGRESS`` with a typed ``agents_to_spawn`` order
            when no change-frame and no worker draft exist yet (AG3-055
            spawn-and-await); ``ESCALATED`` (fail-closed) when no change-frame is
            present and the drafting loop is not wired (or a draft was rejected);
            ``FAILED`` when not configured with a ``story_dir`` or when no review
            is wired.

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
            # AG3-055 produce->consume loop: no validated change-frame yet ->
            # CONSUME a present worker draft, else EMIT a typed spawn order and
            # await (NOT a dead-end escalation). Closes AG3-045's "requires
            # AG3-055" gap. Returns a HandlerResult to await / a re-read frame.
            loop = self._drive_drafting_loop(
                ctx, state, story_dir=story_dir, run_id=run_id
            )
            if loop.terminal is not None:
                return loop.terminal
            change_frame = loop.change_frame
            if change_frame is None:
                # Defensive: a consumed draft must yield a re-readable frame; if
                # not, fail closed rather than proceed without an artifact.
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
        # AG3-047: classify the mandate BEFORE the review (FK-25 §25.4.1) and
        # route the escalating classes fail-closed; the surviving classes
        # (trivial / converged fine-design) flow into the three-stage exit-gate
        # with the mandate-gated Stage-2b decision; an APPROVED gate freezes the
        # change-frame (FK-23 §23.4.3) before COMPLETED.
        return self._run_mandate_flow(
            ctx, state, change_frame, story_dir=story_dir, run_id=run_id
        )

    def _run_mandate_flow(
        self,
        ctx: StoryContext,
        state: PhaseState,
        change_frame: ChangeFrame,
        *,
        story_dir: Path,
        run_id: str,
    ) -> HandlerResult:
        """Classify the mandate, route escalations, then run the gate + freeze.

        Args:
            ctx: The story context for this run.
            state: The incoming phase state.
            change_frame: The validated change-frame.
            story_dir: The story working directory.
            run_id: The bound run id.

        Returns:
            The mapped :class:`HandlerResult`.
        """
        run_design_challenge = True
        if self._mandate is not None:
            routed = self._classify_and_route(
                ctx, state, change_frame, run_id=run_id
            )
            if routed.terminal is not None:
                return routed.terminal
            run_design_challenge = routed.run_design_challenge

        # Run the three-stage exit-gate (Stage 1 -> Stage 2a -> opt. Stage 2b)
        # and map the gate decision onto the phase result (FK-23 §23.5).
        gate_result = self._review.run(  # type: ignore[union-attr]
            change_frame, run_design_challenge=run_design_challenge
        )
        if gate_result.overall_status is ExplorationGateStatus.APPROVED:
            return self._approved_with_freeze(
                state, change_frame, story_dir=story_dir, run_id=run_id
            )
        return self._map_gate_result(state, gate_result)

    def _drive_drafting_loop(
        self,
        ctx: StoryContext,
        state: PhaseState,
        *,
        story_dir: Path,
        run_id: str,
    ) -> _DraftingLoopResult:
        """Run the AG3-055 produce->consume loop for the no-change-frame case.

        Decision (the handler ORCHESTRATES; it does no worker I/O itself):

        * the drafting / presence ports are NOT wired -> legacy fail-closed
          ESCALATED with ``_NO_CHANGE_FRAME_MESSAGE`` (no pseudo-draft);
        * a worker DRAFT is present -> CONSUME it via :class:`ExplorationDrafting`
          (validate + persist the canonical change-frame), re-read the persisted
          frame via the reader and continue (``terminal=None``);
        * no draft -> EMIT a typed ``SpawnRequest`` and return ``IN_PROGRESS``
          (spawn-and-await; the orchestrator spawns the worker and re-invokes).

        Args:
            ctx: The story context for this run.
            state: The incoming phase state.
            story_dir: The story working directory.
            run_id: The bound run id.

        Returns:
            A :class:`_DraftingLoopResult`: a terminal handler result, or the
            re-read change-frame to continue.
        """
        if self._drafting is None or self._draft_presence is None:
            # Legacy plumbing-only construction: no producer wired -> keep the
            # original fail-closed escalation (Option Y; FK-23 §23.3).
            return _DraftingLoopResult(
                terminal=HandlerResult(
                    status=PhaseStatus.ESCALATED,
                    errors=(_NO_CHANGE_FRAME_MESSAGE,),
                    updated_state=self._exploration_state(
                        state, PhaseStatus.ESCALATED, ExplorationGateStatus.PENDING
                    ),
                )
            )
        if not self._draft_presence.worker_draft_present(
            story_dir, story_id=ctx.story_id
        ):
            # The worker has not run yet -> emit a typed spawn order and await.
            return _DraftingLoopResult(
                terminal=self._emit_worker_spawn(state, story_id=ctx.story_id)
            )
        # The worker already ran: CONSUME its draft (validate + persist), then
        # re-read the canonical frame the gate consumes.
        return self._consume_worker_draft(
            ctx, state, story_dir=story_dir, run_id=run_id
        )

    def _emit_worker_spawn(
        self, state: PhaseState, *, story_id: str
    ) -> HandlerResult:
        """Emit a typed exploration-worker spawn order and return IN_PROGRESS.

        AG3-044/054 mechanism (FK-20 §20.5.1 / FK-45 §45.3): the spawn order is a
        typed :class:`SpawnRequest` written into ``PhaseState.agents_to_spawn``
        (the SINGLE typed truth). The engine persists it and re-yields; the
        orchestrator spawns the exploration worker (``SpawnKind.WORKER`` over the
        AG3-044 worker-spawn path with the exploration prompt) and re-invokes the
        phase. There is no EXPLORATION ``SpawnKind`` (the prompt selector picks
        ``worker-exploration`` for the EXPLORATION route). NOT a phase change.

        Args:
            state: The incoming phase state.
            story_id: The story display id (spawn correlation ``target_id``).

        Returns:
            An ``IN_PROGRESS`` ``HandlerResult`` carrying the spawn order.
        """
        spawn_order = SpawnRequest(
            kind=SpawnKind.WORKER,
            spawn_reason=SpawnReason.INITIAL,
            target_id=story_id,
        )
        awaiting_state = self._exploration_state(
            state, PhaseStatus.IN_PROGRESS, ExplorationGateStatus.PENDING
        ).model_copy(update={"agents_to_spawn": [spawn_order]})
        return HandlerResult(
            status=PhaseStatus.IN_PROGRESS,
            yield_status=PauseReason.AWAITING_DESIGN_REVIEW.value,
            updated_state=awaiting_state,
        )

    def _consume_worker_draft(
        self,
        ctx: StoryContext,
        state: PhaseState,
        *,
        story_dir: Path,
        run_id: str,
    ) -> _DraftingLoopResult:
        """Consume the present worker draft and re-read the persisted frame.

        Delegates the validate + persist to the injected
        :class:`ExplorationDrafting` A-core (which orchestrates its own boundary
        ports: the worker-runner reads the raw draft, the sink + writer persist
        the ENTWURF envelope + protected file). The handler then re-reads the
        canonical frame via the reader. A :class:`DraftingError` (empty / foreign
        / invalid draft) escalates fail-closed (no artifact left behind).

        Args:
            ctx: The story context for this run.
            state: The incoming phase state.
            story_dir: The story working directory.
            run_id: The bound run id.

        Returns:
            A :class:`_DraftingLoopResult` with the re-read frame, or a terminal
            fail-closed escalation.
        """
        from agentkit.exploration.drafting.drafting import (
            DraftingError,
            ExplorationDraftRequest,
        )

        try:
            self._drafting.draft(  # type: ignore[union-attr]
                ExplorationDraftRequest(
                    ctx=ctx,
                    story_dir=story_dir,
                    run_id=run_id,
                    invocation_id=f"exploration-{run_id}",
                )
            )
        except DraftingError as exc:
            return _DraftingLoopResult(
                terminal=self._escalate(
                    state,
                    f"Exploration worker draft rejected fail-closed: {exc}",
                    "exploration_draft_rejected: worker must re-produce a valid "
                    "FK-23 ChangeFrame draft",
                )
            )
        change_frame = self._reader.load_change_frame(
            story_id=ctx.story_id, run_id=run_id
        )
        return _DraftingLoopResult(change_frame=change_frame)

    def _classify_and_route(
        self,
        ctx: StoryContext,
        state: PhaseState,
        change_frame: ChangeFrame,
        *,
        run_id: str,
    ) -> _MandateRouting:
        """Classify the mandate, emit telemetry, route escalating classes.

        Args:
            ctx: The story context for this run.
            state: The incoming phase state.
            change_frame: The validated change-frame.
            run_id: The bound run id.

        Returns:
            A :class:`_MandateRouting`: either a terminal ``HandlerResult``
            (escalating class / missing declared-impact port) or the
            ``run_design_challenge`` flag for the surviving classes.
        """
        from agentkit.exploration.mandate.classification import MandateClass

        if self._declared_impact_reader is None or self._telemetry is None:
            # Fail-closed: classifier wired without its mandatory collaborators.
            return _MandateRouting(
                terminal=HandlerResult(
                    status=PhaseStatus.FAILED,
                    errors=(_NO_IMPACT_READER_MESSAGE,),
                    updated_state=self._exploration_state(
                        state, PhaseStatus.FAILED, ExplorationGateStatus.PENDING
                    ),
                )
            )
        declared_impact = self._declared_impact_reader.declared_change_impact(
            story_id=ctx.story_id
        )
        result = self._mandate.classify(change_frame, declared_impact)  # type: ignore[union-attr]
        self._telemetry.emit_classification(
            result, story_id=ctx.story_id, run_id=run_id
        )

        if result.mandate_class is MandateClass.SCOPE_EXPLOSION:
            return _MandateRouting(
                terminal=self._escalate(
                    state, result.decision_summary, _SCOPE_EXPLOSION_REACTION
                )
            )
        if result.mandate_class is MandateClass.IMPACT_ESCALATION:
            return _MandateRouting(
                terminal=self._escalate(
                    state, result.decision_summary, _IMPACT_ESCALATION_REACTION
                )
            )
        if result.mandate_class is MandateClass.FINE_DESIGN:
            terminal = self._run_fine_design(ctx, state, change_frame, run_id=run_id)
            if terminal is not None:
                return _MandateRouting(terminal=terminal)
        return _MandateRouting(run_design_challenge=result.run_design_challenge)

    def _run_fine_design(
        self,
        ctx: StoryContext,
        state: PhaseState,
        change_frame: ChangeFrame,
        *,
        run_id: str,
    ) -> HandlerResult | None:
        """Run the Klasse-2 fine-design subprocess (FK-25 §25.5).

        Emits one ``fine_design_decision`` event per decision (FK-25 §25.8). On
        ``converged`` the flow continues to the review (returns ``None``); on
        ``max_rounds_exceeded`` it escalates fail-closed (FK-25 §25.5.1). When the
        injected evaluator cannot run at all
        (:class:`FineDesignEvaluatorUnavailableError`, FK-25 §25.5.4 -- the
        productive case until the real multi-LLM evaluator exists) it escalates
        fail-closed with the ``fine_design_required`` reaction; it NEVER fabricates
        a converged outcome for a class-2 frame (ZERO DEBT / FAIL-CLOSED).

        Args:
            ctx: The story context for this run.
            state: The incoming phase state.
            change_frame: The validated change-frame.
            run_id: The bound run id.

        Returns:
            ``None`` to continue to the review (converged), or a terminal
            ESCALATED ``HandlerResult`` (round limit or evaluator unavailable),
            or a fail-closed FAILED result when the subprocess is not wired.
        """
        from agentkit.exploration.mandate.fine_design import (
            FineDesignEvaluatorUnavailableError,
        )

        if self._fine_design is None or self._telemetry is None:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=(
                    "Fine-design class requires a wired FineDesignSubprocess + "
                    "telemetry; refusing fail-closed (FK-25 §25.5 / ZERO DEBT).",
                ),
                updated_state=self._exploration_state(
                    state, PhaseStatus.FAILED, ExplorationGateStatus.PENDING
                ),
            )
        try:
            outcome: FineDesignResult = self._fine_design.run(change_frame)
        except FineDesignEvaluatorUnavailableError:
            # FK-25 §25.5.4: no real fine-design discussion could be held (the
            # multi-LLM evaluator is a follow-up). Escalate to a human rather
            # than silently converging a class-2 frame (NO ERROR BYPASSING).
            return self._escalate(
                state,
                _FINE_DESIGN_UNAVAILABLE_REACTION,
                _FINE_DESIGN_UNAVAILABLE_REACTION,
            )
        for decision in outcome.final_design_decisions:
            self._telemetry.emit_fine_design_decision(
                decision, story_id=ctx.story_id, run_id=run_id
            )
        if outcome.status == "max_rounds_exceeded":
            return self._escalate(
                state,
                _FINE_DESIGN_MAX_ROUNDS_REACTION,
                _FINE_DESIGN_MAX_ROUNDS_REACTION,
            )
        return None

    def _approved_with_freeze(
        self,
        state: PhaseState,
        change_frame: ChangeFrame,
        *,
        story_dir: Path,
        run_id: str,
    ) -> HandlerResult:
        """Freeze the change-frame on an APPROVED gate, then COMPLETED.

        FK-23 §23.4.3: the freeze happens ONLY after a PASS gate. There is no
        path here without a Stage-1 PASS (the gate already decided APPROVED).
        When no freeze marker is wired the behaviour is the AG3-046 COMPLETED
        (no freeze) -- a freeze marker makes the artifact write-protected.

        Args:
            state: The incoming phase state.
            change_frame: The gate-passed change-frame.
            story_dir: The story working directory.
            run_id: The bound run id.

        Returns:
            A COMPLETED ``HandlerResult`` (gate APPROVED).
        """
        if self._freeze_marker is not None:
            self._freeze_marker.freeze(
                change_frame,
                story_dir,
                story_id=change_frame.story_id,
                run_id=run_id,
            )
        return HandlerResult(
            status=PhaseStatus.COMPLETED,
            updated_state=self._exploration_state(
                state, PhaseStatus.COMPLETED, ExplorationGateStatus.APPROVED
            ),
        )

    def _escalate(
        self, state: PhaseState, error: str, reaction: str
    ) -> HandlerResult:
        """Build a fail-closed ESCALATED result with a recommended reaction.

        Args:
            state: The incoming phase state.
            error: The operator-facing error detail.
            reaction: The typed recommended reaction (AG3-044 ``suggested_reaction``).

        Returns:
            An ESCALATED ``HandlerResult`` (gate stays PENDING; story stays in
            exploration).
        """
        return HandlerResult(
            status=PhaseStatus.ESCALATED,
            yield_status=PauseReason.AWAITING_DESIGN_REVIEW.value,
            errors=(error,),
            suggested_reaction=reaction,
            updated_state=self._exploration_state(
                state, PhaseStatus.ESCALATED, ExplorationGateStatus.PENDING
            ),
        )

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
