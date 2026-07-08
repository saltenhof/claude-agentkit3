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
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.core_types.attempt import AttemptOutcome, FailureCause
from agentkit.backend.core_types.override import OverrideType
from agentkit.backend.exceptions import PipelineError
from agentkit.backend.pipeline_engine.phase_executor import (
    PhaseState,
    PhaseStatus,
    evolve_phase_state,
)
from agentkit.backend.pipeline_engine.phase_executor.save_phase_completion import (
    save_phase_completion,
)
from agentkit.backend.pipeline_engine.runtime_state import EngineRuntimeState
from agentkit.backend.process.language.model import ExecutionPolicy
from agentkit.backend.state_backend.pipeline_runtime_store import (
    load_node_execution_ledger,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    save_story_context,
)

if TYPE_CHECKING:
    from agentkit.backend.story_context_manager.models import StoryContext


if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.pipeline_engine.lifecycle import (
        HandlerResult,
        PhaseHandler,
        PhaseHandlerRegistry,
    )
    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.backend.process.language.model import (
        OverridePolicy,
        PhaseDefinition,
        WorkflowDefinition,
    )

from agentkit.backend.pipeline_engine.result_handling import (
    EngineResult as EngineResult,
)
from agentkit.backend.pipeline_engine.result_handling import (
    _build_attempt_record,
    _can_enter_phase,
    _evaluate_transitions,
    _override_allowed,
    _process_handler_result_impl,
    _WrapState,
    _yield_point_matches_pause_reason,
)
from agentkit.backend.pipeline_engine.result_handling import (
    _coerce_pause_reason as _coerce_pause_reason,
)
from agentkit.backend.pipeline_engine.result_handling import (
    _engine_status_for as _engine_status_for,
)
from agentkit.backend.pipeline_engine.result_handling import (
    _failure_cause_for_terminal as _failure_cause_for_terminal,
)
from agentkit.backend.pipeline_engine.result_handling import (
    _outcome_for_terminal as _outcome_for_terminal,
)

logger = logging.getLogger(__name__)


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
        # Since AG3-021 state.pause_reason is a PauseReason enum; in the
        # YieldPoint contract yp.status stays a free string, so we compare
        # wire strings via from_yield_status so the synonym mapping from
        # Story §2.1.4 applies here too.
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
        # FK-39 §39.4.4: AttemptRecord FIRST, then PhaseState
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
