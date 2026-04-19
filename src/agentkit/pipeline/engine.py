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

from agentkit.exceptions import PipelineError
from agentkit.pipeline.runtime_state import EngineRuntimeState
from agentkit.process.language.model import ExecutionPolicy
from agentkit.state_backend import (
    AttemptRecord,
    load_node_execution_ledger,
    save_attempt,
    save_phase_snapshot,
    save_phase_state,
    save_story_context,
)
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    StoryContext,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.pipeline.lifecycle import (
        HandlerResult,
        PhaseHandler,
        PhaseHandlerRegistry,
    )
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
            ``"escalated"``, or ``"blocked"``.
        phase: Name of the current or just-completed phase.
        yield_status: Descriptive yield reason (only when
            ``status == "yielded"``).
        next_phase: Suggested next phase name (only when
            ``status == "phase_completed"`` and a valid transition exists).
        errors: Error detail messages.
        attempt_id: Unique identifier for this execution attempt.
    """

    status: str
    phase: str
    yield_status: str | None = None
    next_phase: str | None = None
    errors: tuple[str, ...] = ()
    attempt_id: str | None = None


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
        state: PhaseState,
    ) -> EngineResult:
        """Run the current phase through its handler.

        Steps:
            1. Look up current phase definition in workflow.
            2. Evaluate preconditions -- if ANY fails, return ``"blocked"``.
            3. Get handler from registry.
            4. Call ``handler.on_enter(ctx, state)``.
            5. Based on ``HandlerResult``:
               - COMPLETED: call ``handler.on_exit``, evaluate exit-guards;
                 if any guard fails return ``"failed"``, otherwise save
                 snapshot and evaluate transitions for next phase.
               - PAUSED: save state with yield_status, return ``"yielded"``.
               - FAILED/ESCALATED/BLOCKED: save state, return matching status.
            6. Persist state and attempt record.

        Args:
            ctx: The story context for this pipeline run.
            state: The current phase state.

        Returns:
            An ``EngineResult`` describing the outcome.

        Raises:
            PipelineError: If the phase is not defined in the workflow
                or no handler is registered for it.
        """
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

        override_result = self._apply_pre_execution_override(
            ctx,
            state,
            phase_def,
            attempt_id,
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
                outcome="skipped",
                node_outcome="SKIP",
                flow_status="SKIPPED",
                artifacts=(),
                errors=(policy_skip_reason,),
            )

        # 2. Evaluate preconditions
        can_enter, failure_reasons = _can_enter_phase(
            self._workflow,
            phase_name,
            ctx,
            state,
        )
        if not can_enter:
            self._runtime.record_flow_execution(
                ctx,
                phase_name,
                attempt_id,
                status="BLOCKED",
                node_id=phase_name,
            )
            blocked_state = PhaseState(
                story_id=state.story_id,
                phase=phase_name,
                status=PhaseStatus.BLOCKED,
                errors=failure_reasons,
                attempt_id=attempt_id,
            )
            save_phase_state(self._story_dir, blocked_state)
            attempt = AttemptRecord(
                attempt_id=attempt_id,
                phase=phase_name,
                entered_at=datetime.now(tz=UTC),
                exit_status=PhaseStatus.BLOCKED,
                outcome="blocked",
            )
            save_attempt(self._story_dir, attempt)
            self._runtime.record_node_outcome(
                ctx,
                phase_name,
                attempt_id,
                outcome="FAIL",
            )
            return EngineResult(
                status="blocked",
                phase=phase_name,
                errors=tuple(failure_reasons),
                attempt_id=attempt_id,
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
            result = handler.on_enter(ctx, state)
        except Exception as exc:
            return self._handle_handler_exception(
                ctx,
                phase_name,
                attempt_id,
                [],
                exc,
                story_id=state.story_id,
            )

        # 5. Process handler result
        return self._process_handler_result(
            ctx,
            state,
            phase_def,
            handler,
            result,
            attempt_id,
        )

    def resume_phase(
        self,
        ctx: StoryContext,
        state: PhaseState,
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
            state: The current phase state (must be PAUSED).
            trigger: The resume trigger event name.

        Returns:
            An ``EngineResult`` describing the outcome. Returns
            ``status="failed"`` if the state is not PAUSED or the
            trigger is not valid for the current yield point.
        """
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

        # 2. Verify trigger is valid for a yield point
        valid_trigger = False
        for yp in phase_def.yield_points:
            if yp.status == state.paused_reason and trigger in yp.resume_triggers:
                valid_trigger = True
                break

        if not valid_trigger:
            return EngineResult(
                status="failed",
                phase=phase_name,
                errors=(
                    f"Invalid resume trigger '{trigger}' for phase "
                    f"'{phase_name}' with paused_reason "
                    f"'{state.paused_reason}'",
                ),
            )

        # 3. Get handler and call on_resume
        handler = self._registry.get_handler(phase_name)
        attempt_id = self._runtime.generate_attempt_id(phase_name)

        try:
            result = handler.on_resume(ctx, state, trigger)
        except Exception as exc:
            return self._handle_handler_exception(
                ctx,
                phase_name,
                attempt_id,
                [],
                exc,
                story_id=state.story_id,
            )

        # 4. Process result same as run_phase
        return self._process_handler_result(
            ctx,
            state,
            phase_def,
            handler,
            result,
            attempt_id,
            resume_trigger=trigger,
        )

    def _process_handler_result(
        self,
        ctx: StoryContext,
        state: PhaseState,
        phase_def: PhaseDefinition,
        handler: PhaseHandler,
        result: HandlerResult,
        attempt_id: str,
        *,
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
            resume_trigger: If resuming, the trigger that was used.

        Returns:
            An ``EngineResult`` for the orchestrator.
        """
        phase_name = state.phase

        if result.status == PhaseStatus.COMPLETED:
            # Call on_exit
            try:
                handler.on_exit(ctx, state)
            except Exception as exc:
                logger.warning(
                    "on_exit raised for phase '%s': %s",
                    phase_name,
                    exc,
                )

            # Evaluate exit-guards AFTER handler completion
            completed_state = PhaseState(
                story_id=state.story_id,
                phase=phase_name,
                status=PhaseStatus.COMPLETED,
                attempt_id=attempt_id,
            )
            guard_evals = _evaluate_phase_guards(
                phase_def,
                ctx,
                completed_state,
            )

            # If any exit-guard fails, block the transition
            guard_failures = [g for g in guard_evals if not g.get("passed", False)]
            if guard_failures:
                failure_reasons = [
                    str(g.get("reason", "Guard failed")) for g in guard_failures
                ]
                retry_result = self._apply_retry_policy(
                    ctx,
                    phase_def,
                    attempt_id,
                    failure_reasons=failure_reasons,
                    resume_trigger=resume_trigger,
                )
                if retry_result is not None:
                    return retry_result
                self._runtime.record_flow_execution(
                    ctx,
                    phase_name,
                    attempt_id,
                    status="FAILED",
                    node_id=phase_name,
                    finished_at=datetime.now(tz=UTC),
                )
                failed_state = PhaseState(
                    story_id=state.story_id,
                    phase=phase_name,
                    status=PhaseStatus.FAILED,
                    errors=failure_reasons,
                    attempt_id=attempt_id,
                )
                save_phase_state(self._story_dir, failed_state)

                attempt = AttemptRecord(
                    attempt_id=attempt_id,
                    phase=phase_name,
                    entered_at=datetime.now(tz=UTC),
                    exit_status=PhaseStatus.FAILED,
                    guard_evaluations=tuple(guard_evals),
                    artifacts_produced=result.artifacts_produced,
                    outcome="failed",
                    resume_trigger=resume_trigger,
                )
                save_attempt(self._story_dir, attempt)
                self._runtime.record_node_outcome(
                    ctx,
                    phase_name,
                    attempt_id,
                    outcome="FAIL",
                )

                return EngineResult(
                    status="failed",
                    phase=phase_name,
                    errors=tuple(failure_reasons),
                    attempt_id=attempt_id,
                )

            # Save phase snapshot
            snapshot = PhaseSnapshot(
                story_id=state.story_id,
                phase=phase_name,
                status=PhaseStatus.COMPLETED,
                completed_at=datetime.now(tz=UTC),
                artifacts=list(result.artifacts_produced),
            )
            save_phase_snapshot(self._story_dir, snapshot)

            # Persist phase state
            save_phase_state(self._story_dir, completed_state)
            self._runtime.record_flow_execution(
                ctx,
                phase_name,
                attempt_id,
                status="COMPLETED",
                node_id=phase_name,
                finished_at=datetime.now(tz=UTC),
            )

            # Save attempt record
            attempt = AttemptRecord(
                attempt_id=attempt_id,
                phase=phase_name,
                entered_at=datetime.now(tz=UTC),
                exit_status=PhaseStatus.COMPLETED,
                guard_evaluations=tuple(guard_evals),
                artifacts_produced=result.artifacts_produced,
                outcome="phase_completed",
                resume_trigger=resume_trigger,
            )
            save_attempt(self._story_dir, attempt)
            self._runtime.record_node_outcome(
                ctx,
                phase_name,
                attempt_id,
                outcome="PASS",
            )

            # Evaluate transitions for next phase
            transition = _evaluate_transitions(
                self._workflow,
                ctx,
                completed_state,
            )
            next_phase = transition.target if transition else None

            return EngineResult(
                status="phase_completed",
                phase=phase_name,
                next_phase=next_phase,
                attempt_id=attempt_id,
            )

        if result.status == PhaseStatus.PAUSED:
            # Save paused state
            paused_state = PhaseState(
                story_id=state.story_id,
                phase=phase_name,
                status=PhaseStatus.PAUSED,
                paused_reason=result.yield_status,
                attempt_id=attempt_id,
            )
            save_phase_state(self._story_dir, paused_state)
            self._runtime.record_flow_execution(
                ctx,
                phase_name,
                attempt_id,
                status="YIELDED",
                node_id=phase_name,
            )

            # Save attempt record (no guard evals -- guards are exit-only)
            attempt = AttemptRecord(
                attempt_id=attempt_id,
                phase=phase_name,
                entered_at=datetime.now(tz=UTC),
                exit_status=PhaseStatus.PAUSED,
                artifacts_produced=result.artifacts_produced,
                outcome="yielded",
                yield_status=result.yield_status,
                resume_trigger=resume_trigger,
            )
            save_attempt(self._story_dir, attempt)
            self._runtime.record_node_outcome(
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
            )

        # FAILED, ESCALATED, BLOCKED
        status_map = {
            PhaseStatus.FAILED: "failed",
            PhaseStatus.ESCALATED: "escalated",
            PhaseStatus.BLOCKED: "blocked",
        }
        engine_status = status_map.get(result.status, "failed")

        if result.status == PhaseStatus.FAILED:
            retry_result = self._apply_retry_policy(
                ctx,
                phase_def,
                attempt_id,
                failure_reasons=result.errors,
                artifacts=result.artifacts_produced,
                resume_trigger=resume_trigger,
            )
            if retry_result is not None:
                return retry_result

        error_state = PhaseState(
            story_id=state.story_id,
            phase=phase_name,
            status=result.status,
            errors=list(result.errors),
            attempt_id=attempt_id,
        )
        save_phase_state(self._story_dir, error_state)
        self._runtime.record_flow_execution(
            ctx,
            phase_name,
            attempt_id,
            status=result.status.value.upper(),
            node_id=phase_name,
            finished_at=datetime.now(tz=UTC),
        )

        # No guard evals -- guards are exit-only, handler didn't complete
        attempt = AttemptRecord(
            attempt_id=attempt_id,
            phase=phase_name,
            entered_at=datetime.now(tz=UTC),
            exit_status=result.status,
            artifacts_produced=result.artifacts_produced,
            outcome=engine_status,
            resume_trigger=resume_trigger,
        )
        save_attempt(self._story_dir, attempt)
        self._runtime.record_node_outcome(
            ctx,
            phase_name,
            attempt_id,
            outcome="FAIL",
        )

        return EngineResult(
            status=engine_status,
            phase=phase_name,
            errors=result.errors,
            attempt_id=attempt_id,
        )

    def _handle_handler_exception(
        self,
        ctx: StoryContext,
        phase_name: str,
        attempt_id: str,
        guard_evals: list[dict[str, object]],
        exc: Exception,
        *,
        story_id: str,
    ) -> EngineResult:
        """Handle an exception raised by a phase handler.

        Persists a FAILED state and attempt record, then returns
        an ``EngineResult`` with ``status="failed"``.

        Args:
            phase_name: The phase that was executing.
            attempt_id: The attempt identifier.
            guard_evals: Guard evaluation records for the audit trail.
            exc: The exception that was raised.
            story_id: The story identifier for the failed state.

        Returns:
            An ``EngineResult`` with ``status="failed"`` and error details.
        """
        error_msg = f"Handler for phase '{phase_name}' raised: {exc}"
        logger.error(error_msg, exc_info=exc)

        phase_def = self._workflow.get_phase(phase_name)
        if phase_def is not None:
            retry_result = self._apply_retry_policy(
                ctx,
                phase_def,
                attempt_id,
                failure_reasons=(error_msg,),
            )
            if retry_result is not None:
                return retry_result

        failed_state = PhaseState(
            story_id=story_id,
            phase=phase_name,
            status=PhaseStatus.FAILED,
            errors=[error_msg],
            attempt_id=attempt_id,
        )
        save_phase_state(self._story_dir, failed_state)
        self._runtime.record_flow_execution(
            ctx,
            phase_name,
            attempt_id,
            status="FAILED",
            node_id=phase_name,
            finished_at=datetime.now(tz=UTC),
        )

        attempt = AttemptRecord(
            attempt_id=attempt_id,
            phase=phase_name,
            entered_at=datetime.now(tz=UTC),
            exit_status=PhaseStatus.FAILED,
            guard_evaluations=tuple(guard_evals),
            outcome="failed",
        )
        save_attempt(self._story_dir, attempt)
        self._runtime.record_node_outcome(
            ctx,
            phase_name,
            attempt_id,
            outcome="FAIL",
        )

        return EngineResult(
            status="failed",
            phase=phase_name,
            errors=(error_msg,),
            attempt_id=attempt_id,
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
        outcome: str,
        node_outcome: str,
        flow_status: str,
        artifacts: tuple[str, ...],
        errors: tuple[str, ...] = (),
        next_phase_override: str | None = None,
    ) -> EngineResult:
        """Complete the current node without invoking a handler."""

        phase_name = state.phase
        completed_state = PhaseState(
            story_id=state.story_id,
            phase=phase_name,
            status=PhaseStatus.COMPLETED,
            errors=list(errors),
            attempt_id=attempt_id,
        )
        save_phase_state(self._story_dir, completed_state)
        self._runtime.record_flow_execution(
            ctx,
            phase_name,
            attempt_id,
            status=flow_status,
            node_id=phase_name,
            finished_at=datetime.now(tz=UTC),
        )
        attempt = AttemptRecord(
            attempt_id=attempt_id,
            phase=phase_name,
            entered_at=datetime.now(tz=UTC),
            exit_status=PhaseStatus.COMPLETED,
            artifacts_produced=artifacts,
            outcome=outcome,
        )
        save_attempt(self._story_dir, attempt)
        self._runtime.record_node_outcome(
            ctx,
            phase_name,
            attempt_id,
            outcome=node_outcome,
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
        return EngineResult(
            status="phase_completed",
            phase=phase_name,
            next_phase=next_phase,
            errors=errors,
            attempt_id=attempt_id,
        )

    def _apply_pre_execution_override(
        self,
        ctx: StoryContext,
        state: PhaseState,
        phase_def: PhaseDefinition,
        attempt_id: str,
    ) -> EngineResult | None:
        """Apply supported overrides before handler execution."""

        for record in reversed(self._runtime.iter_active_overrides(ctx)):
            if (
                record.override_type == "skip_node"
                and phase_def.override_policy.allow_skip
                and record.target_node_id in (None, state.phase)
            ):
                self._runtime.consume_override(record)
                return self._complete_without_handler(
                    ctx,
                    state,
                    attempt_id,
                    outcome="skipped_by_override",
                    node_outcome="SKIP",
                    flow_status="SKIPPED",
                    artifacts=(),
                    errors=(record.reason,),
                )

            if (
                record.override_type == "jump_to"
                and phase_def.override_policy.allow_jump
            ):
                destination: str | None = record.target_node_id
                if destination and self._workflow.get_node(destination) is not None:
                    self._runtime.consume_override(record)
                    return self._complete_without_handler(
                        ctx,
                        state,
                        attempt_id,
                        outcome="jumped_by_override",
                        node_outcome="SKIP",
                        flow_status="JUMPED",
                        artifacts=(),
                        errors=(record.reason,),
                        next_phase_override=destination,
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
            if record.override_type == "freeze_retries" and record.target_node_id in (
                None,
                phase_name,
            ):
                self._runtime.consume_override(record)
                return True
        return False

    def _apply_retry_policy(
        self,
        ctx: StoryContext,
        phase_def: PhaseDefinition,
        attempt_id: str,
        *,
        failure_reasons: tuple[str, ...] | list[str],
        artifacts: tuple[str, ...] = (),
        resume_trigger: str | None = None,
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
        failed_state = PhaseState(
            story_id=ctx.story_id,
            phase=phase_name,
            status=PhaseStatus.FAILED,
            errors=list(failure_reasons),
            attempt_id=attempt_id,
        )
        save_phase_state(self._story_dir, failed_state)
        self._runtime.record_flow_execution(
            ctx,
            phase_name,
            attempt_id,
            status="BACKTRACK",
            node_id=retry_policy.backtrack_target,
            finished_at=datetime.now(tz=UTC),
        )
        attempt = AttemptRecord(
            attempt_id=attempt_id,
            phase=phase_name,
            entered_at=datetime.now(tz=UTC),
            exit_status=PhaseStatus.FAILED,
            artifacts_produced=artifacts,
            outcome="backtrack",
            resume_trigger=resume_trigger,
        )
        save_attempt(self._story_dir, attempt)
        self._runtime.record_node_outcome(
            ctx,
            phase_name,
            attempt_id,
            outcome="FAIL",
        )
        return EngineResult(
            status="phase_completed",
            phase=phase_name,
            next_phase=retry_policy.backtrack_target,
            errors=tuple(failure_reasons),
            attempt_id=attempt_id,
        )
