"""Pipeline interpreter that executes workflow definitions.

The engine is the bridge between the declarative workflow DSL (topology)
and the imperative phase handlers (execution). It evaluates preconditions,
guards, calls phase handlers, persists state atomically, and records
attempt history for audit trails.

The engine does NOT make LLM calls or contain business logic -- that
responsibility belongs to the phase handlers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.core_types import PauseReason
from agentkit.core_types.attempt import AttemptOutcome, FailureCause
from agentkit.core_types.override import OverrideType
from agentkit.exceptions import PipelineError
from agentkit.pipeline_engine.phase_envelope.errors import InvalidPauseReasonError
from agentkit.pipeline_engine.phase_executor import (
    PhaseName,
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    evolve_phase_state,
)
from agentkit.pipeline_engine.phase_executor.records import AttemptRecord
from agentkit.pipeline_engine.phase_executor.save_phase_completion import (
    save_phase_completion,
)
from agentkit.pipeline_engine.runtime_state import EngineRuntimeState
from agentkit.process.language.model import ExecutionPolicy
from agentkit.state_backend.store import (
    load_node_execution_ledger,
    save_phase_snapshot,
    save_story_context,
)

if TYPE_CHECKING:
    from agentkit.story_context_manager.models import StoryContext


def _yield_point_matches_pause_reason(
    yield_point_status: str,
    pause_reason: PauseReason | None,
) -> bool:
    """Vergleicht den Yield-Point-Status mit dem persistierten PauseReason.

    ``yield_points[].status`` ist seit AG3-021 weiterhin ein freier String
    im DSL-Vertrag (``YieldPoint``-Dataclass); ``pause_reason`` ist ein
    typisiertes ``PauseReason``-Enum. Der Vergleich erfolgt deshalb ueber
    die Wire-Repraesentation und nutzt ``from_yield_status``, damit
    Synonyme aus AG3-021 §2.1.4 ebenfalls greifen.
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

    Aufrufer (Phase Handler) duerfen seit AG3-021 entweder einen
    ``PauseReason`` direkt oder einen freien String liefern, der via
    ``PauseReason.from_yield_status`` (Story §2.1.4) auf das normierte
    Enum gemappt wird. Unbekannte Strings sind fail-closed: sie werfen
    ``PipelineError``, der Handler-Vertrag haelt damit den Vertrag aus
    FK-39 §39.2.2 (nur drei zulaessige Pause-Reasons).

    Args:
        raw: Vom Handler geliefertes Yield-Status-Datum (Optional).
        phase_name: Phase-Name fuer aussagekraeftige Fehlermeldungen.

    Returns:
        Den normierten ``PauseReason`` oder ``None``, wenn der Handler
        keinen Yield-Grund gemeldet hat.

    Raises:
        PipelineError: Wenn ``raw`` ein nicht-zulaessiger String ist.
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


if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.pipeline_engine.lifecycle import (
        HandlerResult,
        PhaseHandler,
        PhaseHandlerRegistry,
    )
    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.process.language.model import (
        OverridePolicy,
        PhaseDefinition,
        TransitionRule,
        WorkflowDefinition,
    )

logger = logging.getLogger(__name__)


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
    # FK-39 §39.4.4 Crash-Safety: AttemptRecord ZUERST (vor allen weiteren
    # phasenabschliessenden Schreibvorgaengen). record_flow_execution darf
    # erst NACH save_phase_completion durabel werden, sonst kann ein Crash
    # einen "FAILED"-Flow-Eintrag ohne korrespondierenden AttemptRecord
    # hinterlassen.
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
    # FK-39 §39.4.4 Crash-Safety: AttemptRecord ZUERST.
    # save_phase_snapshot und record_flow_execution duerfen erst NACH
    # save_phase_completion durabel werden, sonst kann ein Crash dazu
    # fuehren, dass ein Phase-Snapshot mit "COMPLETED" existiert ohne
    # korrespondierenden AttemptRecord — Recovery liefe dann blind.
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

    # FK-39 §39.4.4: AttemptRecord ZUERST, dann PhaseState
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
    # AG3-021 §2.1.4: yield_status wird typisiert via PauseReason. Aus
    # Migrationsgruenden akzeptieren wir hier weiterhin freie Strings vom
    # Handler und mappen sie via from_yield_status auf das normierte Enum.
    # Unbekannte Werte fuehren zu PipelineError (fail-closed).
    pause_reason = _coerce_pause_reason(result.yield_status, phase_name=phase_name)

    finished_at = datetime.now(tz=UTC)

    # AG3-025 §2.1.4: AttemptRecord traegt outcome=YIELDED, failure_cause=None.
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

    # FK-39 §39.4.4: AttemptRecord ZUERST, dann PhaseState
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
    # FK-39 §39.4.4: AttemptRecord ZUERST, dann PhaseState
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


class PipelineEngine:
    """Interprets a WorkflowDefinition by coordinating handlers and state.

    The engine is the bridge between the declarative DSL (topology) and
    the imperative phase handlers (execution). It:

    - Evaluates preconditions before entering a phase
    - Evaluates exit-guards after handler completion
    - Calls phase handlers (on_enter, on_exit, on_resume)
    - Persists state atomically after each step
    - Records attempt history
    - Handles yield/resume cycles

    The engine does NOT make LLM calls or do any business logic.
    That's the handler's job.

    Args:
        workflow: The immutable workflow definition describing topology.
        registry: Registry mapping phase names to handler implementations.
        story_dir: Root directory for this story's persistent artifacts.
    """

    def __init__(
        self,
        workflow: WorkflowDefinition,
        registry: PhaseHandlerRegistry,
        story_dir: Path,
    ) -> None:
        self._workflow = workflow
        self._registry = registry
        self._story_dir = story_dir
        self._runtime = EngineRuntimeState(workflow, story_dir)

    def run_phase(
        self,
        ctx: StoryContext,
        envelope: PhaseEnvelope,
    ) -> EngineResult:
        """Run the current phase through its handler.

        Steps:
            1. Look up current phase definition in workflow.
            2. Evaluate preconditions -- if ANY fails, return ``"failed"``.
            3. Get handler from registry.
            4. Call ``handler.on_enter(ctx, state)``.
            5. Based on ``HandlerResult``:
               - COMPLETED: call ``handler.on_exit``, evaluate exit-guards;
                 if any guard fails return ``"failed"``, otherwise save
                 snapshot and evaluate transitions for next phase.
               - PAUSED: save state with yield_status, return ``"yielded"``.
               - FAILED/ESCALATED: save state, return matching status.
            6. Persist state and attempt record (AttemptRecord BEFORE PhaseState).

        Args:
            ctx: The story context for this pipeline run.
            envelope: The current phase envelope (durable state +
                ephemeral runtime).

        Returns:
            An ``EngineResult`` describing the outcome.

        Raises:
            PipelineError: If the phase is not defined in the workflow
                or no handler is registered for it.
        """
        state = envelope.state
        phase_name = state.phase
        save_story_context(self._story_dir, ctx)

        # 1. Look up phase definition
        phase_def = self._workflow.get_phase(phase_name)
        if phase_def is None:
            raise PipelineError(
                f"Phase '{phase_name}' is not defined in workflow "
                f"'{self._workflow.name}'",
                detail={
                    "phase": phase_name,
                    "workflow": self._workflow.name,
                    "defined_phases": list(self._workflow.phase_names),
                },
            )

        attempt_id = self._runtime.generate_attempt_id(phase_name)
        started_at = datetime.now(tz=UTC)

        override_result = self._apply_pre_execution_override(
            ctx,
            state,
            phase_def,
            attempt_id,
            started_at=started_at,
        )
        if override_result is not None:
            return override_result

        policy_skip_reason = self._should_skip_for_execution_policy(
            ctx,
            phase_def,
        )
        if policy_skip_reason is not None:
            return self._complete_without_handler(
                ctx,
                state,
                attempt_id,
                outcome=AttemptOutcome.SKIPPED,
                failure_cause=None,
                node_outcome="SKIP",
                flow_status="SKIPPED",
                artifacts=(),
                errors=(policy_skip_reason,),
                started_at=started_at,
            )

        # 2. Evaluate preconditions
        can_enter, failure_reasons = _can_enter_phase(
            self._workflow,
            phase_name,
            ctx,
            state,
        )
        if not can_enter:
            finished_at = datetime.now(tz=UTC)
            failed_state = evolve_phase_state(
                state,
                phase=phase_name,
                status=PhaseStatus.FAILED,
                pause_reason=None,
                escalation_reason=None,
                errors=failure_reasons,
                attempt_id=attempt_id,
            )
            run_id = self._runtime.resolve_run_id(ctx)
            attempt_nr = self._runtime.attempt_number(attempt_id)
            attempt = _build_attempt_record(
                run_id=run_id,
                phase=phase_name,
                attempt_nr=attempt_nr,
                outcome=AttemptOutcome.BLOCKED,
                failure_cause=FailureCause.PRECONDITION_FAILED,
                started_at=started_at,
                ended_at=finished_at,
                detail={"failure_reasons": failure_reasons} if failure_reasons else None,
            )
            # FK-39 §39.4.4 Crash-Safety: AttemptRecord ZUERST,
            # record_flow_execution erst danach.
            save_phase_completion(
                self._story_dir,
                envelope=_WrapState(failed_state),
                attempt_record=attempt,
            )
            self._runtime.record_flow_execution(
                ctx,
                phase_name,
                attempt_id,
                status="FAILED",
                node_id=phase_name,
                finished_at=finished_at,
            )
            self._runtime.record_node_outcome(
                ctx,
                phase_name,
                attempt_id,
                outcome="FAIL",
            )
            self._runtime.record_flow_end(
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
                updated_context=ctx,
            )

        # 3. Get handler (raises PipelineError if not registered)
        handler = self._registry.get_handler(phase_name)

        self._runtime.record_flow_execution(
            ctx,
            phase_name,
            attempt_id,
            status="IN_PROGRESS",
            node_id=phase_name,
        )

        # 4. Call handler.on_enter, catching exceptions
        try:
            result = handler.on_enter(ctx, envelope)
        except Exception as exc:
            return self._handle_handler_exception(
                ctx,
                state,
                phase_name,
                attempt_id,
                [],
                exc,
                started_at=started_at,
            )

        # 5. Process handler result
        return self._process_handler_result(
            ctx,
            state,
            phase_def,
            handler,
            result,
            attempt_id,
            envelope,
            started_at=started_at,
        )

    def resume_phase(
        self,
        ctx: StoryContext,
        envelope: PhaseEnvelope,
        trigger: str,
    ) -> EngineResult:
        """Resume a yielded phase after external input.

        Steps:
            1. Verify ``state.status`` is ``PAUSED``.
            2. Verify trigger is valid for the current yield point.
            3. Call ``handler.on_resume(ctx, state, trigger)``.
            4. Process result same as ``run_phase`` step 5.

        Args:
            ctx: The story context for this pipeline run.
            envelope: The current phase envelope (must be PAUSED).
            trigger: The resume trigger event name.

        Returns:
            An ``EngineResult`` describing the outcome. Returns
            ``status="failed"`` if the state is not PAUSED or the
            trigger is not valid for the current yield point.
        """
        state = envelope.state
        phase_name = state.phase
        save_story_context(self._story_dir, ctx)

        # 1. Verify state is PAUSED
        if state.status != PhaseStatus.PAUSED:
            return EngineResult(
                status="failed",
                phase=phase_name,
                errors=(
                    f"Cannot resume phase '{phase_name}': status is "
                    f"'{state.status.value}', expected 'paused'",
                ),
            )

        # Look up phase definition
        phase_def = self._workflow.get_phase(phase_name)
        if phase_def is None:
            raise PipelineError(
                f"Phase '{phase_name}' is not defined in workflow "
                f"'{self._workflow.name}'",
                detail={
                    "phase": phase_name,
                    "workflow": self._workflow.name,
                },
            )

        # 2. Verify trigger is valid for a yield point.
        # Seit AG3-021 ist state.pause_reason ein PauseReason-Enum; im
        # YieldPoint-Vertrag bleibt yp.status ein freier String, wir
        # vergleichen daher Wire-strings via from_yield_status, damit das
        # Synonym-Mapping aus Story §2.1.4 auch hier greift.
        valid_trigger = False
        for yp in phase_def.yield_points:
            if not _yield_point_matches_pause_reason(
                yp.status, state.pause_reason,
            ):
                continue
            if trigger in yp.resume_triggers:
                valid_trigger = True
                break

        if not valid_trigger:
            return EngineResult(
                status="failed",
                phase=phase_name,
                errors=(
                    f"Invalid resume trigger '{trigger}' for phase "
                    f"'{phase_name}' with pause_reason "
                    f"'{state.pause_reason}'",
                ),
            )

        # 3. Get handler and call on_resume
        handler = self._registry.get_handler(phase_name)
        attempt_id = self._runtime.generate_attempt_id(phase_name)
        started_at = datetime.now(tz=UTC)

        try:
            result = handler.on_resume(ctx, envelope, trigger)
        except Exception as exc:
            return self._handle_handler_exception(
                ctx,
                state,
                phase_name,
                attempt_id,
                [],
                exc,
                started_at=started_at,
            )

        # 4. Process result same as run_phase
        return self._process_handler_result(
            ctx,
            state,
            phase_def,
            handler,
            result,
            attempt_id,
            envelope,
            resume_trigger=trigger,
            started_at=started_at,
        )

    def _process_handler_result(
        self,
        ctx: StoryContext,
        state: PhaseState,
        phase_def: PhaseDefinition,
        handler: PhaseHandler,
        result: HandlerResult,
        attempt_id: str,
        envelope: PhaseEnvelope,
        *,
        started_at: datetime,
        resume_trigger: str | None = None,
    ) -> EngineResult:
        """Process a handler result and persist state and attempt records.

        Called by both ``run_phase`` and ``resume_phase`` after the
        handler has returned.

        Args:
            ctx: The story context.
            state: The phase state before the handler ran.
            phase_def: The phase definition.
            handler: The handler instance (for calling on_exit).
            result: The handler's result.
            attempt_id: The attempt identifier.
            envelope: The full phase envelope (needed for on_exit call).
            started_at: When this attempt was started.
            resume_trigger: If resuming, the trigger that was used.

        Returns:
            An ``EngineResult`` for the orchestrator.
        """
        return _process_handler_result_impl(
            self,
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

    def _handle_handler_exception(
        self,
        ctx: StoryContext,
        state: PhaseState,
        phase_name: str,
        attempt_id: str,
        guard_evals: list[dict[str, object]],
        exc: Exception,
        *,
        started_at: datetime,
    ) -> EngineResult:
        """Handle an exception raised by a phase handler.

        Persists a FAILED state and attempt record (write-ordered), then
        returns an ``EngineResult`` with ``status="failed"``.

        Args:
            phase_name: The phase that was executing.
            attempt_id: The attempt identifier.
            guard_evals: Guard evaluation records for the audit trail.
            exc: The exception that was raised.
            story_id: The story identifier for the failed state.
            started_at: When this attempt was started.

        Returns:
            An ``EngineResult`` with ``status="failed"`` and error details.
        """
        error_msg = f"Handler for phase '{phase_name}' raised: {exc}"
        logger.error(error_msg, exc_info=exc)

        phase_def = self._workflow.get_phase(phase_name)
        if phase_def is not None:
            retry_result = self._apply_retry_policy(
                ctx,
                state,
                phase_def,
                attempt_id,
                failure_reasons=(error_msg,),
                started_at=started_at,
            )
            if retry_result is not None:
                return retry_result

        finished_at = datetime.now(tz=UTC)
        failed_state = evolve_phase_state(
            state,
            phase=phase_name,
            status=PhaseStatus.FAILED,
            pause_reason=None,
            escalation_reason=None,
            errors=[error_msg],
            attempt_id=attempt_id,
        )

        detail: dict[str, object] = {"exception": error_msg}
        if guard_evals:
            detail["guard_evaluations"] = guard_evals

        run_id = self._runtime.resolve_run_id(ctx)
        attempt_nr = self._runtime.attempt_number(attempt_id)
        attempt = _build_attempt_record(
            run_id=run_id,
            phase=phase_name,
            attempt_nr=attempt_nr,
            outcome=AttemptOutcome.FAILED,
            failure_cause=FailureCause.HANDLER_EXCEPTION,
            started_at=started_at,
            ended_at=finished_at,
            detail=detail,
        )
        # FK-39 §39.4.4: AttemptRecord ZUERST, dann PhaseState
        save_phase_completion(
            self._story_dir,
            envelope=_WrapState(failed_state),
            attempt_record=attempt,
        )

        self._runtime.record_flow_execution(
            ctx,
            phase_name,
            attempt_id,
            status="FAILED",
            node_id=phase_name,
            finished_at=finished_at,
        )
        self._runtime.record_node_outcome(
            ctx,
            phase_name,
            attempt_id,
            outcome="FAIL",
        )
        self._runtime.record_flow_end(
            ctx,
            phase_name,
            attempt_id,
            status="FAILED",
            node_id=phase_name,
        )

        return EngineResult(
            status="failed",
            phase=phase_name,
            errors=(error_msg,),
            attempt_id=attempt_id,
            updated_context=ctx,
        )

    def _should_skip_for_execution_policy(
        self,
        ctx: StoryContext,
        phase_def: PhaseDefinition,
    ) -> str | None:
        """Evaluate whether the node should be skipped due to execution policy."""

        existing = load_node_execution_ledger(
            self._story_dir,
            self._workflow.flow_id,
            phase_def.name,
        )
        if existing is None:
            return None

        current_run_id = self._runtime.resolve_run_id(ctx)
        policy = phase_def.execution_policy

        if (
            policy == ExecutionPolicy.ONCE_PER_RUN
            and existing.run_id == current_run_id
            and existing.execution_count > 0
        ):
            return (
                "ExecutionPolicy once_per_run already satisfied "
                f"for node '{phase_def.name}'"
            )

        if policy == ExecutionPolicy.ONCE_PER_STORY and existing.execution_count > 0:
            return (
                "ExecutionPolicy once_per_story already satisfied "
                f"for node '{phase_def.name}'"
            )

        if (
            policy
            in (
                ExecutionPolicy.SKIP_AFTER_SUCCESS,
                ExecutionPolicy.UNTIL_SUCCESS,
            )
            and existing.success_count > 0
        ):
            return (
                f"ExecutionPolicy {policy.value} already satisfied "
                f"for node '{phase_def.name}'"
            )

        return None

    def _complete_without_handler(
        self,
        ctx: StoryContext,
        state: PhaseState,
        attempt_id: str,
        *,
        outcome: AttemptOutcome,
        failure_cause: FailureCause | None,
        node_outcome: str,
        flow_status: str,
        artifacts: tuple[str, ...],
        errors: tuple[str, ...] = (),
        next_phase_override: str | None = None,
        started_at: datetime,
    ) -> EngineResult:
        """Complete the current node without invoking a handler."""

        phase_name = state.phase
        completed_state = evolve_phase_state(
            state,
            phase=phase_name,
            status=PhaseStatus.COMPLETED,
            pause_reason=None,
            escalation_reason=None,
            errors=list(errors),
            attempt_id=attempt_id,
        )
        finished_at = datetime.now(tz=UTC)

        detail: dict[str, object] | None = None
        if artifacts:
            detail = {"artifacts_produced": list(artifacts)}

        run_id = self._runtime.resolve_run_id(ctx)
        attempt_nr = self._runtime.attempt_number(attempt_id)
        attempt = _build_attempt_record(
            run_id=run_id,
            phase=phase_name,
            attempt_nr=attempt_nr,
            outcome=outcome,
            failure_cause=failure_cause,
            started_at=started_at,
            ended_at=finished_at,
            detail=detail,
        )
        # FK-39 §39.4.4 Crash-Safety: AttemptRecord ZUERST,
        # record_flow_execution erst danach.
        save_phase_completion(
            self._story_dir,
            envelope=_WrapState(completed_state),
            attempt_record=attempt,
        )
        self._runtime.record_flow_execution(
            ctx,
            phase_name,
            attempt_id,
            status=flow_status,
            node_id=phase_name,
            finished_at=finished_at,
        )
        self._runtime.record_node_outcome(
            ctx,
            phase_name,
            attempt_id,
            outcome=node_outcome,
            target_node_id=next_phase_override,
        )
        next_phase: str | None
        if next_phase_override is not None:
            next_phase = next_phase_override
        else:
            transition = _evaluate_transitions(
                self._workflow,
                ctx,
                completed_state,
            )
            next_phase = transition.target if transition else None
        if next_phase is None:
            self._runtime.record_flow_end(
                ctx,
                phase_name,
                attempt_id,
                status=flow_status,
                node_id=phase_name,
            )
        return EngineResult(
            status="phase_completed",
            phase=phase_name,
            next_phase=next_phase,
            errors=errors,
            attempt_id=attempt_id,
            updated_context=ctx,
        )

    def _apply_pre_execution_override(
        self,
        ctx: StoryContext,
        state: PhaseState,
        phase_def: PhaseDefinition,
        attempt_id: str,
        *,
        started_at: datetime,
    ) -> EngineResult | None:
        """Apply supported overrides before handler execution."""

        for record in reversed(self._runtime.iter_active_overrides(ctx)):
            if (
                record.override_type is OverrideType.SKIP_NODE
                and _override_allowed(record.override_type, phase_def.override_policy)
                and record.target_node_id in (None, state.phase)
            ):
                self._runtime.consume_override(ctx, record)
                return self._complete_without_handler(
                    ctx,
                    state,
                    attempt_id,
                    outcome=AttemptOutcome.SKIPPED,
                    failure_cause=None,
                    node_outcome="SKIP",
                    flow_status="SKIPPED",
                    artifacts=(),
                    errors=(record.reason,),
                    started_at=started_at,
                )

            if (
                record.override_type is OverrideType.JUMP_TO
                and _override_allowed(record.override_type, phase_def.override_policy)
            ):
                destination: str | None = record.target_node_id
                if destination and self._workflow.get_node(destination) is not None:
                    self._runtime.consume_override(ctx, record)
                    return self._complete_without_handler(
                        ctx,
                        state,
                        attempt_id,
                        outcome=AttemptOutcome.SKIPPED,
                        failure_cause=None,
                        node_outcome="SKIP",
                        flow_status="JUMPED",
                        artifacts=(),
                        errors=(record.reason,),
                        next_phase_override=destination,
                        started_at=started_at,
                    )

        return None

    def _freeze_retries_active(
        self,
        ctx: StoryContext,
        phase_name: str,
        override_policy: OverridePolicy,
    ) -> bool:
        """Return whether a retry-freeze override applies to the current node."""

        if not override_policy.allow_freeze_retries:
            return False
        for record in reversed(self._runtime.iter_active_overrides(ctx)):
            if (
                record.override_type is OverrideType.FREEZE_RETRIES
                and _override_allowed(record.override_type, override_policy)
                and record.target_node_id in (None, phase_name)
            ):
                self._runtime.consume_override(ctx, record)
                return True
        return False

    def _apply_retry_policy(
        self,
        ctx: StoryContext,
        state: PhaseState,
        phase_def: PhaseDefinition,
        attempt_id: str,
        *,
        failure_reasons: tuple[str, ...] | list[str],
        artifacts: tuple[str, ...] = (),
        resume_trigger: str | None = None,
        started_at: datetime,
    ) -> EngineResult | None:
        """Apply retry/backtrack semantics for a failed node execution."""

        retry_policy = phase_def.retry_policy
        if retry_policy is None or retry_policy.backtrack_target is None:
            return None
        if (
            retry_policy.max_attempts is not None
            and self._runtime.attempt_number(attempt_id) >= retry_policy.max_attempts
        ):
            return None
        if self._freeze_retries_active(ctx, phase_def.name, phase_def.override_policy):
            return None
        if self._workflow.get_node(retry_policy.backtrack_target) is None:
            return None

        phase_name = phase_def.name
        failed_state = evolve_phase_state(
            state,
            phase=phase_name,
            status=PhaseStatus.FAILED,
            pause_reason=None,
            escalation_reason=None,
            errors=list(failure_reasons),
            attempt_id=attempt_id,
        )
        finished_at = datetime.now(tz=UTC)

        detail: dict[str, object] | None = None
        if artifacts:
            detail = {"artifacts_produced": list(artifacts)}
        if resume_trigger is not None:
            detail = detail or {}
            detail["resume_trigger"] = resume_trigger

        run_id = self._runtime.resolve_run_id(ctx)
        attempt_nr = self._runtime.attempt_number(attempt_id)
        attempt = _build_attempt_record(
            run_id=run_id,
            phase=phase_name,
            attempt_nr=attempt_nr,
            outcome=AttemptOutcome.FAILED,
            failure_cause=FailureCause.HANDLER_REPORTED_FAILED,
            started_at=started_at,
            ended_at=finished_at,
            detail=detail,
        )
        # FK-39 §39.4.4 Crash-Safety: AttemptRecord ZUERST,
        # record_flow_execution erst danach.
        save_phase_completion(
            self._story_dir,
            envelope=_WrapState(failed_state),
            attempt_record=attempt,
        )
        self._runtime.record_flow_execution(
            ctx,
            phase_name,
            attempt_id,
            status="BACKTRACK",
            node_id=retry_policy.backtrack_target,
            finished_at=finished_at,
        )
        self._runtime.record_node_outcome(
            ctx,
            phase_name,
            attempt_id,
            outcome="BACKTRACK",
            target_node_id=retry_policy.backtrack_target,
        )
        return EngineResult(
            status="phase_completed",
            phase=phase_name,
            next_phase=retry_policy.backtrack_target,
            errors=tuple(failure_reasons),
            attempt_id=attempt_id,
        )
