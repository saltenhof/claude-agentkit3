"""Pipeline interpreter that executes workflow definitions.

The engine is the bridge between the declarative workflow DSL (topology)
and the imperative phase handlers (execution). It evaluates preconditions,
guards, calls phase handlers, persists state atomically, and records
attempt history for audit trails.

The engine does NOT make LLM calls or contain business logic -- that
responsibility belongs to the phase handlers.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.exceptions import PipelineError
from agentkit.phase_state_store import (
    AttemptRecord,
    FlowExecution,
    NodeExecutionLedger,
    load_flow_execution,
    load_node_execution_ledger,
    load_attempts,
    save_attempt,
    save_flow_execution,
    save_node_execution_ledger,
    save_phase_snapshot,
    save_phase_state,
)
from agentkit.story_context_manager.models import PhaseSnapshot, PhaseState, PhaseStatus, StoryContext

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.pipeline.lifecycle import (
        HandlerResult,
        PhaseHandler,
        PhaseHandlerRegistry,
    )
    from agentkit.pipeline.workflow.model import (
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

    def run_phase(
        self, ctx: StoryContext, state: PhaseState,
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

        # 2. Evaluate preconditions
        can_enter, failure_reasons = self.can_enter_phase(
            phase_name, ctx, state,
        )
        if not can_enter:
            attempt_id = self._generate_attempt_id(phase_name)
            self._record_flow_execution(
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
            self._record_node_outcome(
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

        # Generate attempt ID (guards are evaluated post-completion)
        attempt_id = self._generate_attempt_id(phase_name)
        self._record_flow_execution(
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
            ctx, state, phase_def, handler, result,
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
        attempt_id = self._generate_attempt_id(phase_name)

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
            ctx, state, phase_def, handler, result,
            attempt_id, resume_trigger=trigger,
        )

    def evaluate_transitions(
        self, ctx: StoryContext, state: PhaseState,
    ) -> TransitionRule | None:
        """Find the first valid transition from the current phase.

        Evaluates guards in definition order. Returns the first
        transition whose guard passes (or that has no guard). Returns
        ``None`` if no transition is available.

        Args:
            ctx: The story context.
            state: The current phase state.

        Returns:
            The first matching ``TransitionRule``, or ``None``.
        """
        transitions = self._workflow.get_transitions_from(state.phase)
        for transition in transitions:
            if transition.guard is None:
                return transition
            guard_result = transition.guard(ctx, state)
            if guard_result.passed:
                return transition
        return None

    def can_enter_phase(
        self,
        phase_name: str,
        ctx: StoryContext,
        state: PhaseState,
    ) -> tuple[bool, list[str]]:
        """Check whether a phase's preconditions are met.

        Only evaluates preconditions whose ``when`` condition matches
        (or that have no ``when`` condition).

        Args:
            phase_name: The phase to check.
            ctx: The story context.
            state: The current phase state.

        Returns:
            A tuple of ``(True, [])`` if all preconditions pass, or
            ``(False, [list of failure reasons])`` if any fail.
        """
        phase_def = self._workflow.get_phase(phase_name)
        if phase_def is None:
            return (True, [])

        if not phase_def.preconditions:
            return (True, [])

        failures: list[str] = []
        for precondition in phase_def.preconditions:
            # Skip preconditions whose `when` condition does not apply
            if precondition.when is not None:
                try:
                    applies = precondition.when(ctx, state)
                except Exception:
                    # If the when-condition itself fails, treat as applicable
                    applies = True
                if not applies:
                    continue

            guard_result = precondition.guard(ctx, state)
            if not guard_result.passed:
                reason = guard_result.reason or "Precondition failed"
                failures.append(reason)

        if failures:
            return (False, failures)
        return (True, [])

    def _generate_attempt_id(self, phase: str) -> str:
        """Generate a unique attempt ID like ``'setup-001'``.

        Counts existing attempts for the phase and increments.

        Args:
            phase: The phase name.

        Returns:
            A string like ``"setup-001"`` or ``"verify-003"``.
        """
        existing = load_attempts(self._story_dir, phase)
        next_num = len(existing) + 1
        return f"{phase}-{next_num:03d}"

    def _evaluate_guards(
        self,
        phase: PhaseDefinition,
        ctx: StoryContext,
        state: PhaseState,
    ) -> list[dict[str, object]]:
        """Evaluate all exit-guards on a phase and return evaluation records.

        Exit-guards are evaluated after the handler has completed
        successfully. Each record contains the guard name, whether it
        passed, and any failure reason. A guard failure causes the
        phase to transition to FAILED instead of proceeding.

        Args:
            phase: The phase definition containing guards.
            ctx: The story context.
            state: The current phase state.

        Returns:
            List of guard evaluation dictionaries.
        """
        evaluations: list[dict[str, object]] = []
        for guard_fn in phase.guards:
            guard_name = getattr(guard_fn, "guard_name", str(guard_fn))
            try:
                result = guard_fn(ctx, state)
                evaluations.append({
                    "guard": guard_name,
                    "passed": result.passed,
                    "reason": result.reason,
                })
            except Exception as exc:
                evaluations.append({
                    "guard": guard_name,
                    "passed": False,
                    "reason": f"Guard raised exception: {exc}",
                })
        return evaluations

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
                    "on_exit raised for phase '%s': %s", phase_name, exc,
                )

            # Evaluate exit-guards AFTER handler completion
            completed_state = PhaseState(
                story_id=state.story_id,
                phase=phase_name,
                status=PhaseStatus.COMPLETED,
                attempt_id=attempt_id,
            )
            guard_evals = self._evaluate_guards(
                phase_def, ctx, completed_state,
            )

            # If any exit-guard fails, block the transition
            guard_failures = [
                g for g in guard_evals if not g.get("passed", False)
            ]
            if guard_failures:
                failure_reasons = [
                    str(g.get("reason", "Guard failed"))
                    for g in guard_failures
                ]
                self._record_flow_execution(
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
                self._record_node_outcome(
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
            self._record_flow_execution(
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
            self._record_node_outcome(
                ctx,
                phase_name,
                attempt_id,
                outcome="PASS",
            )

            # Evaluate transitions for next phase
            transition = self.evaluate_transitions(ctx, completed_state)
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
            self._record_flow_execution(
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
            self._record_node_outcome(
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

        error_state = PhaseState(
            story_id=state.story_id,
            phase=phase_name,
            status=result.status,
            errors=list(result.errors),
            attempt_id=attempt_id,
        )
        save_phase_state(self._story_dir, error_state)
        self._record_flow_execution(
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
        self._record_node_outcome(
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

        failed_state = PhaseState(
            story_id=story_id,
            phase=phase_name,
            status=PhaseStatus.FAILED,
            errors=[error_msg],
            attempt_id=attempt_id,
        )
        save_phase_state(self._story_dir, failed_state)
        self._record_flow_execution(
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
        self._record_node_outcome(
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

    def _project_key_for(self, ctx: StoryContext) -> str:
        """Derive a stable project key until project registration is explicit."""

        if ctx.project_root is not None:
            return ctx.project_root.name
        if ctx.worktree_path is not None:
            return ctx.worktree_path.parent.name
        return "default-project"

    def _resolve_run_id(self, ctx: StoryContext) -> str:
        """Reuse an existing run id for the flow or derive a deterministic fallback."""

        existing = load_flow_execution(self._story_dir)
        if existing is not None and existing.flow_id == self._workflow.flow_id:
            return existing.run_id
        digest = hashlib.sha1(
            f"{self._project_key_for(ctx)}:{ctx.story_id}:{self._workflow.flow_id}".encode(
                "utf-8",
            ),
            usedforsecurity=False,
        ).hexdigest()[:12]
        return f"run-{digest}"

    def _attempt_number(self, attempt_id: str) -> int:
        """Parse the numeric suffix from an attempt id."""

        try:
            return int(attempt_id.rsplit("-", maxsplit=1)[1])
        except (IndexError, ValueError):
            return 1

    def _record_flow_execution(
        self,
        ctx: StoryContext,
        phase_name: str,
        attempt_id: str,
        *,
        status: str,
        node_id: str | None,
        finished_at: datetime | None = None,
    ) -> None:
        """Persist the current top-level flow execution state."""

        existing = load_flow_execution(self._story_dir)
        run_id = self._resolve_run_id(ctx)
        started_at = (
            existing.started_at
            if existing is not None and existing.flow_id == self._workflow.flow_id
            else datetime.now(tz=UTC)
        )
        record = FlowExecution(
            project_key=self._project_key_for(ctx),
            story_id=ctx.story_id,
            run_id=run_id,
            flow_id=self._workflow.flow_id,
            level=self._workflow.level.value,
            owner=self._workflow.owner,
            parent_flow_id=None,
            status=status,
            current_node_id=node_id or phase_name,
            attempt_no=self._attempt_number(attempt_id),
            started_at=started_at,
            finished_at=finished_at,
        )
        save_flow_execution(self._story_dir, record)

    def _record_node_outcome(
        self,
        ctx: StoryContext,
        node_id: str,
        attempt_id: str,
        *,
        outcome: str,
    ) -> None:
        """Persist node execution history for the current flow node."""

        existing = load_node_execution_ledger(
            self._story_dir,
            self._workflow.flow_id,
            node_id,
        )
        execution_count = 1
        success_count = 1 if outcome == "PASS" else 0
        if existing is not None and existing.run_id == self._resolve_run_id(ctx):
            execution_count = existing.execution_count + 1
            success_count = existing.success_count + (1 if outcome == "PASS" else 0)

        ledger = NodeExecutionLedger(
            project_key=self._project_key_for(ctx),
            story_id=ctx.story_id,
            run_id=self._resolve_run_id(ctx),
            flow_id=self._workflow.flow_id,
            node_id=node_id,
            execution_count=execution_count,
            success_count=success_count,
            last_outcome=outcome,
            last_attempt_no=self._attempt_number(attempt_id),
            last_executed_at=datetime.now(tz=UTC),
        )
        save_node_execution_ledger(self._story_dir, ledger)
