"""Deterministic single-phase dispatch + fail-closed pre-start guard (AG3-054).

This module is the productive wiring between the control-plane API entrypoint
(FK-91 §91.1a) and the deterministic ``PipelineEngine`` (FK-20 §20.1.1):

* :func:`dispatch_phase` runs EXACTLY ONE phase per call (FK-45 §45.1.2). It
  resolves the story's ``PhaseHandlerRegistry`` / ``PipelineEngine`` (the
  composition-root wiring), derives ``start`` vs ``resume`` from the persisted
  phase-state (FK-45 §45.2), runs the engine, and returns the normalized phase
  result + orchestrator reaction (FK-45 §45.3). The engine's own
  phase-transition-enforcement (preconditions / guards / transition graph) is
  CALLED, not rebuilt.

* :class:`PreStartGuard` is the fail-closed pre-start run-admission guard
  (FK-20 §20.8.2, FK-70 §70.8,
  ``story-workflow.invariant.phase_start_requires_release_and_readiness``). It
  fires ONLY before the fresh-run setup start (first call, no phase-state,
  phase=setup) and CONSUMES (does not own) two owner surfaces: Gate 1 = persisted
  ``StoryStatus == Approved`` via the story-service; Gate 2 = computed
  ``PlanningStatus == READY`` + an explicit scheduling admission via the
  execution-planning ``evaluate_scheduling`` top-surface (AG3-100 migration off the
  legacy ``assess_readiness`` source -- one admission truth). Missing Approved OR
  READY OR
  admission -- or an unresolvable / erroring surface -- rejects the setup start
  fail-closed (never default-to-allow). Persisted ``StoryStatus`` (lifecycle) and
  computed ``PlanningStatus`` (READY/BLOCKED) are kept as orthogonal axes;
  READY/BLOCKED are never treated as or written back as a ``StoryStatus``.

Layering: this module lives in ``control_plane`` (an adapter boundary that may
import any component group). The deterministic ``pipeline_engine`` (BC 1) does
NOT import ``control_plane`` -- the dispatch reaches INTO the engine, never the
reverse, so the no-cycle rule (AC 11) holds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.control_plane.models import PhaseDispatchResult
from agentkit.backend.exceptions import PipelineError
from agentkit.backend.pipeline_engine.phase_executor import (
    PhaseName,
    PhaseState,
    PhaseStateProducer,
    PhaseStatus,
    phase_state_mode_from_context,
)
from agentkit.backend.pipeline_engine.phase_executor.models import (
    PhaseStateSpec,
    build_phase_state_from_spec,
)
from agentkit.backend.process.language.phase_transitions import (
    allowed_phase_transition_targets,
    is_valid_phase_transition,
)
from agentkit.backend.story_context_manager.story_model import WireStoryMode

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.pipeline_engine.engine import EngineResult, PipelineEngine
    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.backend.process.language.model import EdgeRule, WorkflowDefinition
    from agentkit.backend.story_context_manager.models import StoryContext


# ---------------------------------------------------------------------------
# Pre-start guard surfaces (consumed, not owned)
# ---------------------------------------------------------------------------


class ApprovalReader(Protocol):
    """Gate 1 read port: the persisted lifecycle ``StoryStatus`` of a story.

    Implemented by the AK3 story-service (BC 3, AG3-014). The guard CONSUMES the
    authoritative persisted status; it never writes story status truth.
    """

    def is_approved(self, project_key: str, story_display_id: str) -> bool:
        """Return ``True`` iff the persisted ``StoryStatus`` is ``Approved``.

        Fail-closed: an unresolvable story (or any read error) must surface as a
        non-approval (``False``) or raise -- never silently approve.
        """
        ...


class SchedulingAdmissionReader(Protocol):
    """Gate 2 read port: computed ``PlanningStatus`` READY + scheduling admission.

    Implemented over execution-planning ``evaluate_scheduling`` (BC 14, FK-70 §70.8;
    AG3-100 migration from the legacy ``assess_readiness`` source). The guard
    CONSUMES the computed readiness/scheduling truth from the SINGLE
    ``evaluate_scheduling`` top-surface; it builds no scheduler and no readiness
    logic of its own, and no second parallel admission/scheduling truth exists.
    """

    def is_ready_and_admitted(self, project_key: str, story_display_id: str) -> bool:
        """Return ``True`` iff the story is computed READY AND scheduling-admitted.

        Fail-closed: an unresolvable assessment (or any read error) must surface
        as ``False`` or raise -- never silently admit.
        """
        ...


def _approval_resolution_error(exc: Exception) -> str:
    return "".join(
        (
            "Pre-start guard rejected setup start: the persisted StoryStatus ",
            f"could not be resolved ({exc}); fail-closed (FK-20 §20.8.2).",
        )
    )


def _scheduling_resolution_error(exc: Exception) -> str:
    return "".join(
        (
            "Pre-start guard rejected setup start: execution-planning ",
            f"readiness/scheduling could not be resolved ({exc}); ",
            "fail-closed (FK-70 §70.8).",
        )
    )


@dataclass(frozen=True)
class PreStartGuard:
    """Fail-closed run-admission guard for the fresh-run setup start (AG3-054).

    Consumes the two owner surfaces and collapses NEITHER axis into the other:
    persisted ``StoryStatus`` (lifecycle, Gate 1) and computed ``PlanningStatus``
    + scheduling admission (Gate 2) are evaluated independently. Either gate
    missing -- or unresolvable -- rejects the start fail-closed.

    Attributes:
        approval_reader: Gate 1 surface (persisted ``StoryStatus == Approved``).
        scheduling_reader: Gate 2 surface (computed READY + scheduling admission).
    """

    approval_reader: ApprovalReader
    scheduling_reader: SchedulingAdmissionReader

    def evaluate(
        self,
        *,
        project_key: str,
        story_display_id: str,
    ) -> str | None:
        """Evaluate run-admission for a fresh-run setup start.

        Args:
            project_key: Owning project key.
            story_display_id: The story's display id (e.g. ``"AG3-054"``).

        Returns:
            ``None`` when the start is admitted (Approved AND READY+admission);
            otherwise a human-readable rejection reason string. Any surface that
            raises is mapped to a fail-closed rejection reason -- never to
            admission.
        """
        # Gate 1 -- persisted lifecycle release (fail-closed on any read error).
        try:
            approved = self.approval_reader.is_approved(project_key, story_display_id)
        # Fail-closed: never default-allow.
        except Exception as exc:  # noqa: BLE001
            return _approval_resolution_error(exc)
        if not approved:
            return "".join(
                (
                    "Pre-start guard rejected setup start: StoryStatus is not ",
                    "Approved (Gate 1, business release missing; FK-20 §20.8.2).",
                )
            )

        # Gate 2 -- computed READY + scheduling admission (orthogonal axis).
        try:
            admitted = self.scheduling_reader.is_ready_and_admitted(
                project_key, story_display_id
            )
        # Fail-closed: never default-allow.
        except Exception as exc:  # noqa: BLE001
            return _scheduling_resolution_error(exc)
        if not admitted:
            return "".join(
                (
                    "Pre-start guard rejected setup start: ExecutionPlanning ",
                    "does not report computed PlanningStatus READY with a ",
                    "scheduling admission (Gate 2; FK-70 §70.6.1/§70.8).",
                )
            )
        return None


# ---------------------------------------------------------------------------
# Single-phase dispatch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseDispatcher:
    """Deterministic single-phase dispatcher (FK-45 §45.1.2).

    Owns no engine / transition / handler mechanic: it resolves the run's engine,
    applies the pre-start guard before the fresh-run setup start, derives
    start-vs-resume from the persisted phase-state, runs EXACTLY ONE phase through
    the engine, and normalizes the engine result. PAUSED/ESCALATED never starts a
    follow-up phase (the dispatch returns; the orchestrator decides next).

    Attributes:
        engine_factory: Resolves a wired ``PipelineEngine`` for a story run
            (composition-root ``build_pipeline_engine``). Injected so tests drive
            the productive composition without a self-build.
        guard_factory: Resolves the fail-closed pre-start run-admission guard FOR
            THIS RUN (E7 fix): both Gate-1 (approval) and Gate-2 (scheduling)
            readers must read from the RUN'S authoritative store/project root, not
            cwd. The dispatcher is built once but ``dispatch`` carries the run
            ``ctx``, so the guard is resolved per run from ``ctx`` (e.g. its
            ``project_root``). The factory is consulted ONLY before a fresh-run
            setup start.
        resume_trigger_resolver: Maps a phase mutation request's ``detail`` to the
            resume trigger string for a same-phase resume of a PAUSED phase.
    """

    engine_factory: Callable[[StoryContext], PipelineEngine]
    guard_factory: Callable[[StoryContext], PreStartGuard]
    resume_trigger_resolver: Callable[[dict[str, object]], str | None] = field(
        default=lambda detail: _default_resume_trigger(detail)
    )
    #: E1: a fresh-setup-start precheck that returns a rejection reason when the
    #: run's authoritative GitHub setup coordinates cannot be resolved (so setup is
    #: never dispatched against empty/dummy coordinates), or ``None`` to admit. The
    #: productive factory wires the real resolver; the default no-op is for the
    #: dispatch-contract tests that STUB the setup boundary (no real GitHub).
    setup_coordinates_check: Callable[[StoryContext], str | None] = field(
        default=lambda ctx: None
    )

    def dispatch(
        self,
        *,
        ctx: StoryContext,
        phase: str,
        story_dir: Path,
        run_id: str,
        run_admitted: bool,
        detail: dict[str, object] | None = None,
    ) -> PhaseDispatchResult:
        """Dispatch exactly ONE phase for a story run (FK-45 §45.1.2 / §45.3).

        Args:
            ctx: The run's story context (carries ``story_id``, ``story_type``,
                ``project_key``).
            phase: The requested phase name (``setup`` / ``exploration`` /
                ``implementation`` / ``closure``).
            story_dir: The story working directory (engine persistence root).
            run_id: The authoritative run id of THIS dispatch. Identifies the run
                whose admission the caller evaluated; carried for diagnostics and
                to keep the admission decision unambiguously RUN-scoped (AG3-054
                ERROR-1).
            run_admitted: Whether THIS exact run is already admitted, decided
                RUN-scoped by the caller (control-plane ``_run_admission_evidence``:
                a run-matched session binding OR a committed setup ``phase_start``
                for ``(project, story, run_id)``). This is the ONLY input to the
                fresh-setup / first-call ADMISSION gate -- story-scoped phase-state
                (``existing``) is NOT consulted for admission, so an OLD run's
                phase-state for the SAME story (e.g. after ``reset-escalation``,
                which mints a new run id but reuses the per-story story_dir) can
                never make a NEW, un-admitted run "not fresh" and thereby SKIP the
                fail-closed pre-start guard (the fail-open this fix closes).
                Story-scoped phase-state still drives the engine's transition /
                resume MECHANICS below -- only the admission gate is run-scoped.
            detail: Optional request detail (resume trigger resolution).

        Returns:
            A normalized :class:`PhaseDispatchResult`. A pre-start-guard rejection
            or an invalid first-call phase is ``status="rejected"`` with no engine
            entry; otherwise the engine outcome is normalized to the FK-45 §45.3
            reaction.
        """
        from agentkit.backend.process.language.definitions import resolve_workflow

        del run_id  # RUN scope is carried by ``run_admitted``; id kept for clarity.
        detail = detail or {}
        workflow = resolve_workflow(ctx.story_type)
        phase_names = tuple(workflow.phase_names)
        existing = _load_phase_state(ctx, story_dir, phase_names)

        admission_rejection = self._admission_rejection(
            ctx=ctx, phase=phase, run_admitted=run_admitted
        )
        if admission_rejection is not None:
            return _rejected(phase, admission_rejection)

        # The engine is built AFTER the first-call/guard/coordinate checks. The
        # productive engine factory resolves the run's REAL ``SetupConfig``
        # (owner/repo/issue) from ``ctx`` and threads it into the setup handler.
        try:
            engine = self.engine_factory(ctx)
        except PipelineError as exc:
            return _rejected(phase, str(exc))

        # Phase-transition-enforcement (FK-45 §45.2 step 2-4): a forward request to
        # a DIFFERENT phase is legal only along a workflow edge from the persisted
        # phase, only when that phase already COMPLETED, AND only when that edge's
        # GUARD is satisfied for this story/ctx. Resume of the same phase is not a
        # transition (handled below). Fail-closed: an out-of-graph jump, a
        # not-yet-completed predecessor, or a guard-rejected edge never enters the
        # phase.
        state_rejection = _state_reentry_rejection(workflow, ctx, existing, phase)
        if state_rejection is not None:
            return _rejected(phase, state_rejection)

        envelope = _build_envelope(existing, ctx, phase, engine=engine)
        run_result = _run_engine_entry(
            engine=engine,
            ctx=ctx,
            envelope=envelope,
            phase=phase,
            existing=existing,
            detail=detail,
            resume_trigger_resolver=self.resume_trigger_resolver,
        )
        if isinstance(run_result, PhaseDispatchResult):
            return run_result
        return _normalize(run_result)

    def _admission_rejection(
        self,
        *,
        ctx: StoryContext,
        phase: str,
        run_admitted: bool,
    ) -> str | None:
        first_call_rejection = _first_call_rejection(phase, run_admitted)
        if first_call_rejection is not None:
            return first_call_rejection
        if run_admitted or phase != PhaseName.SETUP.value:
            return None
        rejection = self.guard_factory(ctx).evaluate(
            project_key=ctx.project_key,
            story_display_id=ctx.story_id,
        )
        if rejection is not None:
            return rejection
        return self.setup_coordinates_check(ctx)


def _first_call_rejection(phase: str, run_admitted: bool) -> str | None:
    if run_admitted or phase == PhaseName.SETUP.value:
        return None
    return "".join(
        (
            "First call for this run has no run-scoped admission evidence; ",
            f"only 'setup' may start a fresh run, not {phase!r} ",
            "(FK-45 §45.2 / AG3-054 ERROR-1).",
        )
    )


def _state_reentry_rejection(
    workflow: WorkflowDefinition,
    ctx: StoryContext,
    existing: PhaseState | None,
    phase: str,
) -> str | None:
    if existing is None:
        return None
    if existing.phase != phase:
        return _enforce_transition(workflow, ctx, existing, phase)
    if existing.status == PhaseStatus.PAUSED:
        return None
    return _same_phase_reentry_reason(phase, existing.status)


def _run_engine_entry(
    *,
    engine: PipelineEngine,
    ctx: StoryContext,
    envelope: PhaseEnvelope,
    phase: str,
    existing: PhaseState | None,
    detail: dict[str, object],
    resume_trigger_resolver: Callable[[dict[str, object]], str | None],
) -> EngineResult | PhaseDispatchResult:
    if not _is_paused_resume(existing, phase):
        return engine.run_phase(ctx, envelope)
    trigger = resume_trigger_resolver(detail)
    if trigger is None:
        return _rejected(
            phase,
            f"Resume of PAUSED phase {phase!r} requires a resume trigger "
            "in request detail (FK-45 §45.2).",
        )
    return engine.resume_phase(ctx, envelope, trigger)


def _is_paused_resume(existing: PhaseState | None, phase: str) -> bool:
    return (
        existing is not None
        and existing.phase == phase
        and existing.status == PhaseStatus.PAUSED
    )


def _default_resume_trigger(detail: dict[str, object]) -> str | None:
    """Read the resume trigger from a phase mutation request detail."""
    trigger = detail.get("resume_trigger")
    return trigger if isinstance(trigger, str) and trigger else None


def _load_phase_state(
    ctx: StoryContext,
    story_dir: Path,
    phase_names: tuple[str, ...],
) -> PhaseState | None:
    """Load the most recent persisted phase-state for the run, or ``None``.

    Reads through the ``PhaseEnvelopeStore`` (the engine's own persistence facade
    -- one truth). The canonical phase-state row is keyed by ``(story_id, phase)``;
    the dispatch probes every workflow phase (in workflow order) so a resumed /
    advanced run is found regardless of which phase it last persisted.
    """
    from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
    from agentkit.backend.state_backend.store.phase_envelope_repository import (
        StateBackendPhaseEnvelopeRepository,
    )

    store = PhaseEnvelopeStore(StateBackendPhaseEnvelopeRepository(story_dir))
    latest: PhaseState | None = None
    for phase_name in phase_names:
        try:
            phase_enum = PhaseName(phase_name)
        except ValueError:
            continue
        envelope = store.load(ctx.story_id, phase_enum)
        if envelope is not None:
            latest = envelope.state
    return latest


def _enforce_transition(
    workflow: WorkflowDefinition,
    ctx: StoryContext,
    existing: PhaseState,
    phase: str,
) -> str | None:
    """Validate a forward phase transition against the typed workflow graph.

    FK-45 §45.2: a transition to a DIFFERENT phase is legal only when (a) a
    workflow edge exists from the persisted phase to the requested phase, (b) the
    persisted phase already reached ``COMPLETED``, AND (c) that edge's GUARD is
    satisfied for this story/ctx. The guard check enforces the mode-dependent
    semantic preconditions (FK-45 §45.2 "semantic preconditions"): e.g. the
    guarded ``setup -> exploration`` edge (``mode_is_exploration``) keeps an
    execution-route story out of exploration (exploration-skip), and the guarded
    ``exploration -> implementation`` edge (``exploration_gate_approved``) keeps
    an un-approved gate out of implementation. Returns a rejection reason string
    when illegal, or ``None`` when the transition is admissible.

    The guard evaluation DELEGATES to the workflow's own typed transition guards
    (``EdgeRule.guard(ctx, state)``) -- the same predicate the engine's
    ``_evaluate_transitions`` runs on the forward edge -- so no second partial
    copy of the transition logic is built.
    """
    from_phase = str(existing.phase)
    if not is_valid_phase_transition(existing.phase, phase):
        return (
            f"Invalid phase transition from_phase={from_phase!r} "
            f"to_phase={phase!r} from_status={existing.status.value!r}: not in "
            "the derived phase-transition superset "
            f"(allowed transitions from {from_phase!r}: "
            f"{allowed_phase_transition_targets(existing.phase)}; FK-45 §45.2)."
        )
    edges = workflow.get_transitions_from(existing.phase)
    targets = {edge.target for edge in edges}
    if phase not in targets:
        return (
            f"Invalid phase transition from_phase={from_phase!r} "
            f"to_phase={phase!r} from_status={existing.status.value!r}: not a "
            f"workflow edge (allowed transitions: {sorted(targets)}; "
            "FK-45 §45.2)."
        )
    if existing.status != PhaseStatus.COMPLETED:
        return (
            f"Invalid phase transition {existing.phase!r} -> {phase!r}: the "
            f"predecessor phase is {existing.status.value!r}, not 'completed' "
            "(FK-45 §45.2)."
        )
    # W9 fix: mirror the engine's ``_evaluate_transitions`` EXACTLY. The engine
    # iterates the outgoing edges in definition order (``get_transitions_from``
    # already returns them priority-sorted) and SELECTS THE FIRST whose guard
    # passes -- regardless of that edge's target. A transition to the requested
    # phase is therefore admissible ONLY when that first-passing edge targets the
    # requested phase. Admitting whenever *any* edge to the target passes would
    # admit a transition the engine would never select (it would have taken an
    # earlier-passing edge to a DIFFERENT phase first). An unguarded edge passes
    # immediately, so it is the first-passing edge in its slot.
    selected = _first_passing_edge(edges, ctx, existing)
    if selected is None:
        return (
            f"Invalid phase transition {existing.phase!r} -> {phase!r}: no "
            "outgoing transition guard is satisfied for this story, so the "
            "engine would select no edge (FK-45 §45.2 semantic precondition)."
        )
    if selected.target == phase:
        return None
    return (
        f"Invalid phase transition {existing.phase!r} -> {phase!r}: the engine "
        f"would select the first-passing edge to {selected.target!r} "
        f"(guard {_guard_name(selected.guard)!r}), not the requested phase "
        f"{phase!r} (FK-45 §45.2 -- dispatch mirrors engine edge ordering)."
    )


def _first_passing_edge(
    edges: tuple[EdgeRule, ...],
    ctx: StoryContext,
    state: PhaseState,
) -> EdgeRule | None:
    """Return the FIRST outgoing edge whose guard passes (engine semantics).

    Byte-for-byte the selection rule of the engine's ``_evaluate_transitions``
    (FK-45 §45.2): iterate the (priority-ordered) outgoing edges and return the
    first one with no guard or a passing guard; ``None`` when none passes.
    """
    for edge in edges:
        if edge.guard is None:
            return edge
        if edge.guard(ctx, state).passed:
            return edge
    return None


def _same_phase_reentry_reason(phase: str, status: PhaseStatus) -> str:
    """Build the rejection reason for an illegal same-phase re-entry (E5)."""
    if status == PhaseStatus.COMPLETED:
        return (
            f"Phase {phase!r} already completed for this run; a same-phase start "
            "is legal only as a PAUSED-resume. Rejecting the duplicate start "
            "(idempotent already-completed, no re-execution; FK-45 §45.2)."
        )
    return (
        f"Phase {phase!r} is {status.value!r} for this run; a same-phase start is "
        "legal only as a PAUSED-resume. Recovery of a failed/escalated "
        "phase is the operator-recovery CLI's job (FK-45 §45.4), not a re-start "
        "via the standard entrypoint (fail-closed; FK-45 §45.2)."
    )


def _guard_name(guard_fn: object) -> str:
    """Return a guard's registered name (or its ``repr``) for diagnostics."""
    return str(getattr(guard_fn, "guard_name", guard_fn))


def _build_envelope(
    existing: PhaseState | None,
    ctx: StoryContext,
    phase: str,
    *,
    engine: PipelineEngine,
) -> PhaseEnvelope:
    """Build the engine envelope for the requested phase.

    Resume / same-phase re-entry uses the persisted state; a forward transition
    or a fresh start wraps a PENDING state for the requested phase.
    """
    from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore

    if existing is not None and existing.phase == phase:
        return PhaseEnvelopeStore.make_fresh_envelope(existing)
    now = datetime.now(tz=UTC)
    fresh = build_phase_state_from_spec(
        PhaseStateSpec(
            story_id=ctx.story_id,
            run_id=engine._runtime.resolve_run_id(ctx),
            phase=phase,
            status=PhaseStatus.PENDING,
            mode=phase_state_mode_from_context(
                execution_route=ctx.execution_route,
                fast=ctx.mode is WireStoryMode.FAST,
            ),
            story_type=ctx.story_type,
            attempt=1,
            started_at=now,
            phase_entered_at=now,
            producer=PhaseStateProducer(type="script", name="dispatch-phase"),
        )
    )
    return PhaseEnvelopeStore.make_fresh_envelope(fresh)


# Engine ``EngineResult.status`` -> normalized (status, reaction). The reaction
# follows the FK-45 §45.3 reaction table outcome class.
_REACTION_BY_STATUS: dict[str, tuple[str, str]] = {
    "phase_completed": ("phase_completed", "advance"),
    "yielded": ("yielded", "await_external"),
    "failed": ("failed", "escalate"),
    "escalated": ("escalated", "escalate"),
}


def _normalize(result: EngineResult) -> PhaseDispatchResult:
    """Normalize an engine result to the FK-45 §45.3 dispatch contract."""
    status, reaction = _REACTION_BY_STATUS.get(
        result.status, ("failed", "escalate")
    )
    # A completed phase that suggests a next phase is the orchestrator's signal to
    # run the next worker; a completed terminal phase (no next) just advances.
    if status == "phase_completed" and result.next_phase is not None:
        reaction = "run_worker"
    return PhaseDispatchResult(
        phase=result.phase,
        status=status,
        reaction=reaction,
        dispatched=True,
        next_phase=result.next_phase,
        yield_status=result.yield_status,
        errors=tuple(result.errors),
    )


def _rejected(phase: str, reason: str) -> PhaseDispatchResult:
    """Build a fail-closed rejection result (no engine entry)."""
    return PhaseDispatchResult(
        phase=phase,
        status="rejected",
        reaction="rejected",
        dispatched=False,
        rejection_reason=reason,
    )


# ---------------------------------------------------------------------------
# Productive default surfaces
# ---------------------------------------------------------------------------


def build_story_service_approval_reader(
    store_dir: Path | None = None,
) -> ApprovalReader:
    """Build the productive Gate 1 reader over the AK3 story-service (AG3-014).

    E7 fix: the persisted ``StoryStatus`` is read from the RUN'S store, not cwd.
    The story-service is rooted at ``store_dir`` (the run's project/store root) via
    its ``StateBackendStoryRepository``, so an Approved run is not wrongly rejected
    -- nor a colliding cwd story wrongly admitted.
    """
    from agentkit.backend.state_backend.store.story_repository import (
        StateBackendStoryRepository,
    )
    from agentkit.backend.story_context_manager.service import StoryService
    from agentkit.backend.story_context_manager.story_model import StoryStatus

    service = StoryService(
        story_repository=StateBackendStoryRepository(store_dir),
    )

    @dataclass(frozen=True)
    class _StoryServiceApprovalReader:
        def is_approved(self, project_key: str, story_display_id: str) -> bool:
            del project_key
            story = service.get_story(story_display_id)
            if story is None:
                return False
            return story.status is StoryStatus.APPROVED

    return _StoryServiceApprovalReader()


def build_execution_planning_admission_reader(
    store_dir: Path | None = None,
) -> SchedulingAdmissionReader:
    """Build the productive Gate 2 reader over execution-planning ``evaluate_scheduling``.

    AG3-100 (FK-70 §70.8 / FK-20 §20.8.2): the admission gate consumes the SINGLE
    ``evaluate_scheduling`` top-surface -- the mandatory call the ``PipelineEngine``
    must make before any story start. READY + scheduling admission is consumed as:
    the story is a ``ready_candidate`` of the evaluation. This MIGRATES the one
    Gate-2 admission path off the legacy ``assess_readiness`` source; no second
    parallel admission/scheduling truth is built (the legacy ``assess_readiness``
    surface keeps serving the dashboard ``planning/next-ready`` detail endpoint, but
    is no longer the admission source).

    AG3-099 (FK-70 §70.10.2): the dependency edges feeding ``evaluate_scheduling``
    are read from the BC-9 planning projection path (the same path planning writes
    go to), so admission/readiness and planning writes share one source of truth --
    no read/write split onto the legacy ``story_dependencies`` table.
    """
    from agentkit.backend.bootstrap.composition_root import (
        build_planning_story_dependency_repository,
    )
    from agentkit.backend.execution_planning.dependency_graph import DependencyGraph
    from agentkit.backend.execution_planning.entities import (
        ExecutionCapacityBudgets,
        ParallelizationConfig,
    )
    from agentkit.backend.execution_planning.scheduling import evaluate_scheduling
    from agentkit.backend.state_backend.store.parallelization_config_repository import (
        StateBackendParallelizationConfigRepository,
    )
    from agentkit.backend.state_backend.store.planning_story_repository import (
        StateBackendPlanningStoryRepository,
    )

    story_repo = StateBackendPlanningStoryRepository(store_dir)
    # AG3-099 FK-70 §70.10.2 (SINGLE SOURCE OF TRUTH): admission/readiness must
    # read dependency edges from the SAME planning projection path that planning
    # writes go to (``planning_dependency_edge``), not the legacy direct
    # ``story_dependencies`` table. Using the legacy
    # ``StateBackendStoryDependencyRepository`` here would split read truth from
    # write truth -- a story READY-blocking edge written via the planning path
    # would be invisible to admission.
    dep_repo = build_planning_story_dependency_repository(store_dir)
    config_repo = StateBackendParallelizationConfigRepository(store_dir)

    def _budgets(
        project_key: str,
        stories: list[object],
    ) -> ExecutionCapacityBudgets:
        config = config_repo.get(project_key)
        if config is None:
            config = ParallelizationConfig(
                project_key=project_key,
                max_parallel_stories=max(1, len(stories)),
            )
        repo_cap = config.max_parallel_stories_per_repo or config.max_parallel_stories
        return ExecutionCapacityBudgets(
            repo_parallel_cap=repo_cap,
            merge_risk_cap=config.max_parallel_stories,
            api_rate_limit_cap=config.max_parallel_stories,
            llm_pool_cap=config.max_parallel_stories,
            ci_capacity_cap=config.max_parallel_stories,
        )

    @dataclass(frozen=True)
    class _ExecutionPlanningAdmissionReader:
        def is_ready_and_admitted(
            self, project_key: str, story_display_id: str
        ) -> bool:
            stories = story_repo.list_for_project(project_key)
            edges = dep_repo.list_for_project(project_key)
            evaluation = evaluate_scheduling(
                project_key=project_key,
                stories=stories,
                dependency_graph=DependencyGraph(edges),
                budgets=_budgets(project_key, list(stories)),
            )
            return evaluation.is_ready(story_display_id)

    return _ExecutionPlanningAdmissionReader()


def build_pre_start_guard(store_dir: Path | None = None) -> PreStartGuard:
    """Build the productive fail-closed pre-start guard (Gate 1 + Gate 2).

    E7 fix: BOTH the approval (Gate 1) and scheduling (Gate 2) readers are rooted at
    the run's ``store_dir`` so the admission decision reads the run's authoritative
    store (SINGLE SOURCE OF TRUTH), never cwd.
    """
    return PreStartGuard(
        approval_reader=build_story_service_approval_reader(store_dir),
        scheduling_reader=build_execution_planning_admission_reader(store_dir),
    )


def build_phase_dispatcher() -> PhaseDispatcher:
    """Build the productive single-phase dispatcher over the composition root.

    The engine factory resolves a wired ``PipelineEngine`` per run via
    ``build_pipeline_engine`` (one truth; no self-build). ``story_dir`` is derived
    from the story context's ``project_root`` + story id. E1 fix: the productive
    engine factory builds a REAL ``SetupConfig`` from the run ``ctx`` (the GitHub
    coordinates resolved from the run's project config), never an empty dummy.

    E7 fix: the pre-start run-admission guard is resolved PER RUN from ``ctx`` so
    both Gate-1 (approval) and Gate-2 (scheduling) readers read from the RUN'S
    authoritative store/project root, not cwd.
    """
    from agentkit.backend.bootstrap.composition_root import (
        SetupCoordinatesUnavailableError,
        build_pipeline_engine,
        build_setup_config_for_run,
    )

    def _engine_factory(ctx: StoryContext) -> PipelineEngine:
        story_dir = _resolve_story_dir(ctx)
        # E1: thread the run's REAL ``SetupConfig`` (owner/repo/issue from ``ctx``)
        # into the engine. The setup handler is built eagerly with the rest of the
        # registry; a non-setup dispatch never enters it, so unresolvable
        # coordinates here must NOT block a legitimate follow-up phase. The
        # fail-closed REJECTION of a FRESH SETUP start on unresolvable coordinates
        # is enforced separately in :meth:`PhaseDispatcher.dispatch` (the
        # ``_require_setup_coordinates`` precheck), where the requested phase is
        # known. So: best-effort here, hard-reject there.
        try:
            setup_config: object | None = build_setup_config_for_run(ctx)
        except SetupCoordinatesUnavailableError:
            setup_config = None
        return build_pipeline_engine(
            story_dir,
            story_type=ctx.story_type,
            project_key=ctx.project_key,
            setup_config=setup_config,
        )

    def _guard_factory(ctx: StoryContext) -> PreStartGuard:
        # The run's store root is its project root (the SINGLE store the run
        # uses). Both admission reads target it (E7).
        return build_pre_start_guard(ctx.project_root)

    def _require_setup_coordinates(ctx: StoryContext) -> str | None:
        # E1: a FRESH setup start MUST have authoritative GitHub coordinates;
        # never run setup against empty/dummy coordinates. Returns a rejection
        # reason when unresolvable, else ``None``.
        try:
            build_setup_config_for_run(ctx)
        except SetupCoordinatesUnavailableError as exc:
            return str(exc)
        return None

    return PhaseDispatcher(
        engine_factory=_engine_factory,
        guard_factory=_guard_factory,
        setup_coordinates_check=_require_setup_coordinates,
    )


def _resolve_story_dir(ctx: StoryContext) -> Path:
    """Resolve the story working directory from the run context (fail-closed)."""
    from agentkit.backend.installer.paths import story_dir

    if ctx.project_root is None:
        raise PipelineError(
            "Cannot dispatch a phase without a resolved project_root on the "
            "StoryContext (fail-closed).",
            detail={"story_id": ctx.story_id},
        )
    return story_dir(ctx.project_root, ctx.story_id)
