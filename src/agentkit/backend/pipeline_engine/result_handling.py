"""Pipeline transition and handler-result semantics."""


from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.core_types import PauseReason
from agentkit.backend.core_types.attempt import AttemptOutcome, FailureCause
from agentkit.backend.core_types.override import OverrideType
from agentkit.backend.exceptions import PipelineError
from agentkit.backend.pipeline_engine.phase_envelope.errors import InvalidPauseReasonError
from agentkit.backend.pipeline_engine.phase_executor import (
    PhaseName,
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    evolve_phase_state,
)
from agentkit.backend.pipeline_engine.phase_executor.records import AttemptRecord
from agentkit.backend.pipeline_engine.phase_executor.save_phase_completion import (
    save_phase_completion,
)
from agentkit.backend.state_backend.pipeline_runtime_store import (
    save_phase_snapshot,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agentkit.backend.pipeline_engine.engine import PipelineEngine
    from agentkit.backend.pipeline_engine.lifecycle import (
        HandlerResult,
        PhaseHandler,
    )
    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.backend.process.language.model import (
        OverridePolicy,
        PhaseDefinition,
        TransitionRule,
        WorkflowDefinition,
    )
    from agentkit.backend.story_context_manager.models import StoryContext


def _yield_point_matches_pause_reason(
    yield_point_status: str,
    pause_reason: PauseReason | None,
) -> bool:
    """Compare the yield-point status against the persisted PauseReason.

    ``yield_points[].status`` is, since AG3-021, still a free string in the
    DSL contract (``YieldPoint`` dataclass); ``pause_reason`` is a typed
    ``PauseReason`` enum. The comparison therefore goes through the wire
    representation and uses ``from_yield_status`` so that synonyms from
    AG3-021 §2.1.4 are honoured too.
    """
    if pause_reason is None:
        return False
    try:
        return PauseReason.from_yield_status(yield_point_status) is pause_reason
    except ValueError:
        return False


def _coerce_pause_reason(
    raw: str | PauseReason | None,
    *,
    phase_name: str,
) -> PauseReason | None:
    """Convert handler yield_status into a typed PauseReason or None.

    Callers (phase handlers) may, since AG3-021, supply either a
    ``PauseReason`` directly or a free string that is mapped onto the
    normalised enum via ``PauseReason.from_yield_status`` (Story §2.1.4).
    Unknown strings are fail-closed: they raise ``PipelineError``, so the
    handler contract upholds the contract from FK-39 §39.2.2 (the
    permitted pause reasons defined there).

    Args:
        raw: The yield-status datum supplied by the handler (optional).
        phase_name: Phase name for meaningful error messages.

    Returns:
        The normalised ``PauseReason``, or ``None`` when the handler
        reported no yield reason.

    Raises:
        PipelineError: When ``raw`` is an impermissible string.
    """
    if raw is None:
        return None
    if isinstance(raw, PauseReason):
        return raw
    try:
        return PauseReason.from_yield_status(raw)
    except ValueError as exc:
        raise InvalidPauseReasonError(
            f"Handler for phase {phase_name!r} produced unknown yield_status "
            f"{raw!r}; PauseReason allows only "
            f"{[m.value for m in PauseReason]}",
            detail={"phase": phase_name, "raw": raw},
        ) from exc


def _coerce_phase_name(phase: str) -> PhaseName:
    """Coerce a phase string to ``PhaseName``, falling back if unknown."""
    try:
        return PhaseName(phase)
    except ValueError:
        # Unknown phase names (e.g. custom workflow phases) default to
        # IMPLEMENTATION for audit purposes; this is a best-effort coercion.
        # Strictly typed phases are AG3-041 scope.
        return PhaseName.IMPLEMENTATION


def _build_attempt_record(
    *,
    run_id: str,
    phase: str,
    attempt_nr: int,
    outcome: AttemptOutcome,
    failure_cause: FailureCause | None,
    started_at: datetime,
    ended_at: datetime,
    detail: dict[str, object] | None = None,
) -> AttemptRecord:
    """Construct a typed ``AttemptRecord`` (FK-39 §39.4.1)."""
    return AttemptRecord(
        run_id=run_id,
        phase=_coerce_phase_name(phase),
        attempt=attempt_nr,
        outcome=outcome,
        failure_cause=failure_cause,
        started_at=started_at,
        ended_at=ended_at,
        detail=detail,
    )


@dataclass(frozen=True)
class EngineResult:
    """Result of an engine operation (run_phase or resume_phase).

    Tells the orchestrator what happened so it can decide what to do next.

    Args:
        status: One of ``"phase_completed"``, ``"yielded"``, ``"failed"``,
            or ``"escalated"``.
        phase: Name of the current or just-completed phase.
        yield_status: Descriptive yield reason (only when
            ``status == "yielded"``).
        next_phase: Suggested next phase name (only when
            ``status == "phase_completed"`` and a valid transition exists).
        errors: Error detail messages.
        attempt_id: Unique identifier for this execution attempt.
        suggested_reaction: Typed escalation-reaction carrier propagated from
            the terminal :class:`HandlerResult` (AG3-044 AC6, FK-26 §26.11.2).
            When a handler ESCALATES/BLOCKS with a concrete recommended reaction
            (e.g. a BLOCKED worker manifest's blocker details), the engine
            forwards it here so production callers read the structured blocker
            payload rather than only the human-summary ``errors`` string.
            ``None`` when the handler produced no such recommendation.
    """

    status: str
    phase: str
    yield_status: str | None = None
    next_phase: str | None = None
    errors: tuple[str, ...] = ()
    attempt_id: str | None = None
    updated_context: StoryContext | None = None
    suggested_reaction: str | None = None


def _evaluate_transitions(
    workflow: WorkflowDefinition,
    ctx: StoryContext,
    state: PhaseState,
) -> TransitionRule | None:
    """Find the first valid transition from the current phase."""

    transitions = workflow.get_transitions_from(state.phase)
    for transition in transitions:
        if transition.guard is None:
            return transition
        guard_result = transition.guard(ctx, state)
        if guard_result.passed:
            return transition
    return None


def _can_enter_phase(
    workflow: WorkflowDefinition,
    phase_name: str,
    ctx: StoryContext,
    state: PhaseState,
) -> tuple[bool, list[str]]:
    """Check whether a phase's preconditions are met."""

    phase_def = workflow.get_phase(phase_name)
    if phase_def is None or not phase_def.preconditions:
        return (True, [])

    failures: list[str] = []
    for precondition in phase_def.preconditions:
        if precondition.when is not None:
            try:
                applies = precondition.when(ctx, state)
            except Exception:
                applies = True
            if not applies:
                continue

        guard_result = precondition.guard(ctx, state)
        if not guard_result.passed:
            failures.append(guard_result.reason or "Precondition failed")

    if failures:
        return (False, failures)
    return (True, [])


def _evaluate_phase_guards(
    phase: PhaseDefinition,
    ctx: StoryContext,
    state: PhaseState,
) -> list[dict[str, object]]:
    """Evaluate all exit-guards on a phase and return evaluation records."""

    evaluations: list[dict[str, object]] = []
    for guard_fn in phase.guards:
        guard_name = getattr(guard_fn, "guard_name", str(guard_fn))
        try:
            result = guard_fn(ctx, state)
            evaluations.append(
                {
                    "guard": guard_name,
                    "passed": result.passed,
                    "reason": result.reason,
                }
            )
        except Exception as exc:
            evaluations.append(
                {
                    "guard": guard_name,
                    "passed": False,
                    "reason": f"Guard raised exception: {exc}",
                }
            )
    return evaluations


def _override_allowed(override_type: OverrideType, policy: OverridePolicy) -> bool:
    """Return whether a node policy admits an override type."""

    match override_type:
        case OverrideType.SKIP_NODE:
            return policy.allow_skip
        case OverrideType.FORCE_GATE_PASS:
            return policy.allow_force_pass
        case OverrideType.FORCE_GATE_FAIL:
            return policy.allow_force_fail
        case OverrideType.JUMP_TO:
            return policy.allow_jump
        case OverrideType.TRUNCATE_FLOW:
            return policy.allow_truncate
        case OverrideType.FREEZE_RETRIES:
            return policy.allow_freeze_retries
    raise PipelineError(f"Unknown override type: {override_type!r}")


def _completed_state_for(
    state: PhaseState,
    attempt_id: str,
    result: HandlerResult,
) -> PhaseState:
    source_state = result.updated_state or state
    return evolve_phase_state(
        source_state,
        phase=state.phase,
        status=PhaseStatus.COMPLETED,
        pause_reason=None,
        escalation_reason=None,
        errors=list(result.errors),
        attempt_id=attempt_id,
    )


def _snapshot_evidence(state: PhaseState) -> dict[str, object]:
    if state.payload is None:
        return {}
    return state.payload.model_dump(mode="json")


def _transition_target_for(
    engine: PipelineEngine,
    ctx: StoryContext,
    completed_state: PhaseState,
) -> str | None:
    transition = _evaluate_transitions(
        engine._workflow,
        ctx,
        completed_state,
    )
    return transition.target if transition else None


def _handle_guard_failure_result(
    engine: PipelineEngine,
    ctx: StoryContext,
    state: PhaseState,
    phase_def: PhaseDefinition,
    result: HandlerResult,
    attempt_id: str,
    guard_evals: list[dict[str, object]],
    *,
    started_at: datetime,
    resume_trigger: str | None,
) -> EngineResult:
    phase_name = state.phase
    failure_reasons = [
        str(guard_eval.get("reason", "Guard failed"))
        for guard_eval in guard_evals
        if not guard_eval.get("passed", False)
    ]
    retry_result = engine._apply_retry_policy(
        ctx,
        state,
        phase_def,
        attempt_id,
        failure_reasons=failure_reasons,
        resume_trigger=resume_trigger,
        started_at=started_at,
    )
    if retry_result is not None:
        return retry_result

    finished_at = datetime.now(tz=UTC)

    detail: dict[str, object] = {"guard_evaluations": guard_evals}
    if result.artifacts_produced:
        detail["artifacts_produced"] = list(result.artifacts_produced)
    if resume_trigger is not None:
        detail["resume_trigger"] = resume_trigger

    run_id = engine._runtime.resolve_run_id(ctx)
    attempt_nr = engine._runtime.attempt_number(attempt_id)
    attempt_record = _build_attempt_record(
        run_id=run_id,
        phase=phase_name,
        attempt_nr=attempt_nr,
        outcome=AttemptOutcome.BLOCKED,
        failure_cause=FailureCause.GUARD_REJECTED,
        started_at=started_at,
        ended_at=finished_at,
        detail=detail if detail else None,
    )
    new_state = evolve_phase_state(
        state,
        phase=phase_name,
        status=PhaseStatus.FAILED,
        pause_reason=None,
        escalation_reason=None,
        errors=failure_reasons,
        attempt_id=attempt_id,
    )
    # FK-39 §39.4.4 crash safety: AttemptRecord FIRST (before all further
    # phase-completing writes). record_flow_execution must only become durable
    # AFTER save_phase_completion, otherwise a crash could leave a "FAILED" flow
    # entry without a corresponding AttemptRecord.
    save_phase_completion(
        engine._story_dir,
        envelope=_WrapState(new_state),
        attempt_record=attempt_record,
    )
    engine._runtime.record_flow_execution(
        ctx,
        phase_name,
        attempt_id,
        status="FAILED",
        node_id=phase_name,
        finished_at=finished_at,
    )
    engine._runtime.record_node_outcome(
        ctx,
        phase_name,
        attempt_id,
        outcome="FAIL",
    )
    engine._runtime.record_flow_end(
        ctx,
        phase_name,
        attempt_id,
        status="FAILED",
        node_id=phase_name,
    )
    return EngineResult(
        status="failed",
        phase=phase_name,
        errors=tuple(failure_reasons),
        attempt_id=attempt_id,
        updated_context=result.updated_context,
    )


def _handle_completed_result(
    engine: PipelineEngine,
    ctx: StoryContext,
    state: PhaseState,
    phase_def: PhaseDefinition,
    handler: PhaseHandler,
    result: HandlerResult,
    attempt_id: str,
    envelope: PhaseEnvelope,
    *,
    started_at: datetime,
    resume_trigger: str | None,
) -> EngineResult:
    phase_name = state.phase
    try:
        handler.on_exit(ctx, envelope)
    except Exception as exc:
        logger.warning(
            "on_exit raised for phase '%s': %s",
            phase_name,
            exc,
        )

    completed_state = _completed_state_for(state, attempt_id, result)
    guard_evals = _evaluate_phase_guards(
        phase_def,
        ctx,
        completed_state,
    )
    if any(not guard_eval.get("passed", False) for guard_eval in guard_evals):
        return _handle_guard_failure_result(
            engine,
            ctx,
            state,
            phase_def,
            result,
            attempt_id,
            guard_evals,
            started_at=started_at,
            resume_trigger=resume_trigger,
        )

    finished_at = datetime.now(tz=UTC)
    detail: dict[str, object] | None = None
    if guard_evals:
        detail = {"guard_evaluations": guard_evals}
    if result.artifacts_produced:
        detail = detail or {}
        detail["artifacts_produced"] = list(result.artifacts_produced)
    if resume_trigger is not None:
        detail = detail or {}
        detail["resume_trigger"] = resume_trigger

    run_id = engine._runtime.resolve_run_id(ctx)
    attempt_nr = engine._runtime.attempt_number(attempt_id)
    attempt_record = _build_attempt_record(
        run_id=run_id,
        phase=phase_name,
        attempt_nr=attempt_nr,
        outcome=AttemptOutcome.COMPLETED,
        failure_cause=None,
        started_at=started_at,
        ended_at=finished_at,
        detail=detail,
    )
    # FK-39 §39.4.4 crash safety: AttemptRecord FIRST.
    # save_phase_snapshot and record_flow_execution must only become durable
    # AFTER save_phase_completion, otherwise a crash could lead to a phase
    # snapshot with "COMPLETED" existing without a corresponding AttemptRecord —
    # recovery would then run blind.
    save_phase_completion(
        engine._story_dir,
        envelope=_WrapState(completed_state),
        attempt_record=attempt_record,
    )
    save_phase_snapshot(
        engine._story_dir,
        PhaseSnapshot(
            story_id=state.story_id,
            phase=phase_name,
            status=PhaseStatus.COMPLETED,
            completed_at=datetime.now(tz=UTC),
            artifacts=list(result.artifacts_produced),
            evidence=_snapshot_evidence(completed_state),
        ),
    )
    engine._runtime.record_flow_execution(
        ctx,
        phase_name,
        attempt_id,
        status="COMPLETED",
        node_id=phase_name,
        finished_at=datetime.now(tz=UTC),
    )
    engine._runtime.record_node_outcome(
        ctx,
        phase_name,
        attempt_id,
        outcome="PASS",
    )
    next_phase = _transition_target_for(engine, ctx, completed_state)
    if next_phase is None:
        engine._runtime.record_flow_end(
            ctx,
            phase_name,
            attempt_id,
            status="COMPLETED",
            node_id=phase_name,
        )
    return EngineResult(
        status="phase_completed",
        phase=phase_name,
        next_phase=next_phase,
        attempt_id=attempt_id,
        updated_context=result.updated_context or ctx,
    )


def _handle_reentry_result(
    engine: PipelineEngine,
    ctx: StoryContext,
    state: PhaseState,
    result: HandlerResult,
    attempt_id: str,
    *,
    started_at: datetime,
    resume_trigger: str | None,
) -> EngineResult:
    """Persist an IN_PROGRESS handler result carrying ``agents_to_spawn``.

    FK-20 §20.5.1 / FK-45 §45.3: the subflow-internal remediation loop does NOT
    transition the phase. The Implementation handler returns ``IN_PROGRESS``
    with ``agents_to_spawn=[remediation_worker]`` (NOT ``PAUSED`` — there is no
    ``AWAITING_REMEDIATION`` PauseReason; the phase stays its own active phase).
    The engine persists that state (preserving ``agents_to_spawn`` so the
    orchestrator can read the spawn order) and reports ``"yielded"`` so the
    orchestrator spawns the worker and re-invokes the phase — no phase change.

    Args:
        engine: The pipeline engine.
        ctx: The run story context.
        state: The current phase state (pre-handler).
        result: The handler result (status IN_PROGRESS, agents_to_spawn set).
        attempt_id: The current attempt id.
        started_at: Attempt start timestamp.
        resume_trigger: Optional resume trigger string.

    Returns:
        An ``EngineResult`` with ``status="yielded"`` for orchestrator re-entry.
    """
    phase_name = state.phase
    finished_at = datetime.now(tz=UTC)
    run_id = engine._runtime.resolve_run_id(ctx)
    attempt_nr = engine._runtime.attempt_number(attempt_id)
    detail: dict[str, object] | None = None
    if result.artifacts_produced:
        detail = {"artifacts_produced": list(result.artifacts_produced)}
    if resume_trigger is not None:
        detail = detail or {}
        detail["resume_trigger"] = resume_trigger

    attempt_record = _build_attempt_record(
        run_id=run_id,
        phase=phase_name,
        attempt_nr=attempt_nr,
        outcome=AttemptOutcome.YIELDED,
        failure_cause=None,
        started_at=started_at,
        ended_at=finished_at,
        detail=detail,
    )

    source = result.updated_state or state
    reentry_state = evolve_phase_state(
        source,
        phase=phase_name,
        status=PhaseStatus.IN_PROGRESS,
        pause_reason=None,
        escalation_reason=None,
        errors=list(result.errors),
        attempt_id=attempt_id,
        # Preserve the typed spawn order so the orchestrator reads it (FK-45
        # §45.3). Dropping it here would make the spawn dead — fail-open.
        agents_to_spawn=list(source.agents_to_spawn),
    )

    # FK-39 §39.4.4: AttemptRecord FIRST, then PhaseState
    save_phase_completion(
        engine._story_dir,
        envelope=_WrapState(reentry_state),
        attempt_record=attempt_record,
    )

    engine._runtime.record_flow_execution(
        ctx,
        phase_name,
        attempt_id,
        status="YIELDED",
        node_id=phase_name,
    )
    engine._runtime.record_node_outcome(
        ctx,
        phase_name,
        attempt_id,
        outcome="YIELD",
    )
    return EngineResult(
        status="yielded",
        phase=phase_name,
        yield_status=result.yield_status,
        attempt_id=attempt_id,
        updated_context=result.updated_context or ctx,
    )


def _handle_paused_result(
    engine: PipelineEngine,
    ctx: StoryContext,
    state: PhaseState,
    result: HandlerResult,
    attempt_id: str,
    *,
    started_at: datetime,
    resume_trigger: str | None,
) -> EngineResult:
    phase_name = state.phase
    # AG3-021 §2.1.4: yield_status is typed via PauseReason. For migration
    # reasons we still accept free strings from the handler here and map them
    # via from_yield_status onto the normalised enum. Unknown values lead to
    # PipelineError (fail-closed).
    pause_reason = _coerce_pause_reason(result.yield_status, phase_name=phase_name)

    finished_at = datetime.now(tz=UTC)

    # AG3-025 §2.1.4: AttemptRecord carries outcome=YIELDED, failure_cause=None.
    # pause_reason lives exclusively in PhaseEnvelope.state.pause_reason.
    # No pause_reason/yield_status in AttemptRecord.detail.
    run_id = engine._runtime.resolve_run_id(ctx)
    attempt_nr = engine._runtime.attempt_number(attempt_id)
    detail: dict[str, object] | None = None
    if result.artifacts_produced:
        detail = {"artifacts_produced": list(result.artifacts_produced)}
    if resume_trigger is not None:
        detail = detail or {}
        detail["resume_trigger"] = resume_trigger

    attempt_record = _build_attempt_record(
        run_id=run_id,
        phase=phase_name,
        attempt_nr=attempt_nr,
        outcome=AttemptOutcome.YIELDED,
        failure_cause=None,
        started_at=started_at,
        ended_at=finished_at,
        detail=detail,
    )

    source = result.updated_state or state
    paused_state = evolve_phase_state(
        source,
        phase=phase_name,
        status=PhaseStatus.PAUSED,
        pause_reason=pause_reason,
        escalation_reason=None,
        attempt_id=attempt_id,
    )

    # FK-39 §39.4.4: AttemptRecord FIRST, then PhaseState
    save_phase_completion(
        engine._story_dir,
        envelope=_WrapState(paused_state),
        attempt_record=attempt_record,
    )

    engine._runtime.record_flow_execution(
        ctx,
        phase_name,
        attempt_id,
        status="YIELDED",
        node_id=phase_name,
    )
    engine._runtime.record_node_outcome(
        ctx,
        phase_name,
        attempt_id,
        outcome="YIELD",
    )
    return EngineResult(
        status="yielded",
        phase=phase_name,
        yield_status=result.yield_status,
        attempt_id=attempt_id,
        updated_context=result.updated_context or ctx,
    )


def _engine_status_for(result_status: PhaseStatus) -> str:
    status_map = {
        PhaseStatus.FAILED: "failed",
        PhaseStatus.ESCALATED: "escalated",
    }
    return status_map.get(result_status, "failed")


def _outcome_for_terminal(result_status: PhaseStatus) -> AttemptOutcome:
    outcome_map = {
        PhaseStatus.FAILED: AttemptOutcome.FAILED,
        PhaseStatus.ESCALATED: AttemptOutcome.ESCALATED,
    }
    return outcome_map.get(result_status, AttemptOutcome.FAILED)


def _failure_cause_for_terminal(result_status: PhaseStatus) -> FailureCause:
    if result_status == PhaseStatus.ESCALATED:
        return FailureCause.HANDLER_REPORTED_ESCALATED
    return FailureCause.HANDLER_REPORTED_FAILED


def _handle_terminal_result(
    engine: PipelineEngine,
    ctx: StoryContext,
    state: PhaseState,
    phase_def: PhaseDefinition,
    result: HandlerResult,
    attempt_id: str,
    *,
    started_at: datetime,
    resume_trigger: str | None,
) -> EngineResult:
    phase_name = state.phase
    engine_status = _engine_status_for(result.status)
    if result.status == PhaseStatus.FAILED:
        retry_result = engine._apply_retry_policy(
            ctx,
            state,
            phase_def,
            attempt_id,
            failure_reasons=result.errors,
            artifacts=result.artifacts_produced,
            resume_trigger=resume_trigger,
            started_at=started_at,
        )
        if retry_result is not None:
            return retry_result

    finished_at = datetime.now(tz=UTC)
    source = result.updated_state or state
    terminal_state = evolve_phase_state(
        source,
        phase=phase_name,
        status=result.status,
        pause_reason=None,
        escalation_reason=source.escalation_reason
        if result.status is PhaseStatus.ESCALATED
        else None,
        errors=list(result.errors),
        attempt_id=attempt_id,
    )

    detail: dict[str, object] | None = None
    if result.artifacts_produced:
        detail = {"artifacts_produced": list(result.artifacts_produced)}
    if resume_trigger is not None:
        detail = detail or {}
        detail["resume_trigger"] = resume_trigger

    run_id = engine._runtime.resolve_run_id(ctx)
    attempt_nr = engine._runtime.attempt_number(attempt_id)
    outcome = _outcome_for_terminal(result.status)
    failure_cause = _failure_cause_for_terminal(result.status)
    attempt_record = _build_attempt_record(
        run_id=run_id,
        phase=phase_name,
        attempt_nr=attempt_nr,
        outcome=outcome,
        failure_cause=failure_cause,
        started_at=started_at,
        ended_at=finished_at,
        detail=detail,
    )
    # FK-39 §39.4.4: AttemptRecord FIRST, then PhaseState
    save_phase_completion(
        engine._story_dir,
        envelope=_WrapState(terminal_state),
        attempt_record=attempt_record,
    )

    engine._runtime.record_flow_execution(
        ctx,
        phase_name,
        attempt_id,
        status=result.status.value.upper(),
        node_id=phase_name,
        finished_at=datetime.now(tz=UTC),
    )
    engine._runtime.record_node_outcome(
        ctx,
        phase_name,
        attempt_id,
        outcome="FAIL",
    )
    engine._runtime.record_flow_end(
        ctx,
        phase_name,
        attempt_id,
        status=result.status.value.upper(),
        node_id=phase_name,
    )
    return EngineResult(
        status=engine_status,
        phase=phase_name,
        errors=result.errors,
        attempt_id=attempt_id,
        updated_context=result.updated_context,
        # AG3-044 AC6 (FK-26 §26.11.2): propagate the typed escalation reaction
        # to the caller. A BLOCKED/ESCALATED handler carries the structured
        # blocker payload here; dropping it would leave production callers with
        # only the human-summary errors string (fail-open on the model).
        suggested_reaction=result.suggested_reaction,
    )


def _process_handler_result_impl(
    engine: PipelineEngine,
    ctx: StoryContext,
    state: PhaseState,
    phase_def: PhaseDefinition,
    handler: PhaseHandler,
    result: HandlerResult,
    attempt_id: str,
    envelope: PhaseEnvelope,
    *,
    started_at: datetime,
    resume_trigger: str | None,
) -> EngineResult:
    if result.status == PhaseStatus.COMPLETED:
        return _handle_completed_result(
            engine,
            ctx,
            state,
            phase_def,
            handler,
            result,
            attempt_id,
            envelope,
            started_at=started_at,
            resume_trigger=resume_trigger,
        )
    if result.status == PhaseStatus.PAUSED:
        return _handle_paused_result(
            engine,
            ctx,
            state,
            result,
            attempt_id,
            started_at=started_at,
            resume_trigger=resume_trigger,
        )
    # FK-20 §20.5.1: a subflow-internal remediation continuation returns
    # IN_PROGRESS with agents_to_spawn set (no phase transition). The engine
    # persists it and re-yields to the orchestrator for the spawn.
    if (
        result.status == PhaseStatus.IN_PROGRESS
        and result.updated_state is not None
        and result.updated_state.agents_to_spawn
    ):
        return _handle_reentry_result(
            engine,
            ctx,
            state,
            result,
            attempt_id,
            started_at=started_at,
            resume_trigger=resume_trigger,
        )
    return _handle_terminal_result(
        engine,
        ctx,
        state,
        phase_def,
        result,
        attempt_id,
        started_at=started_at,
        resume_trigger=resume_trigger,
    )


class _WrapState:
    """Minimal envelope-like wrapper that exposes only ``.state``.

    Satisfies the ``EnvelopeWithState`` protocol used by
    ``save_phase_completion``, allowing the engine to pass a raw
    ``PhaseState`` without constructing a full ``PhaseEnvelope``.
    """

    def __init__(self, state: PhaseState) -> None:
        self._state = state

    @property
    def state(self) -> PhaseState:
        return self._state
