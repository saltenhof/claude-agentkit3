"""High-level pipeline runner that orchestrates a complete story execution.

Provides :func:`run_pipeline`, a convenience function that drives a
:class:`~agentkit.backend.pipeline_engine.engine.PipelineEngine` through all phases
of a workflow until completion, yield, failure, or escalation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.pipeline_engine.engine import EngineResult, PipelineEngine
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.pipeline_engine.phase_executor import (
    PhaseName,
    PhaseStateProducer,
    PhaseStatus,
    phase_state_mode_from_context,
)
from agentkit.backend.pipeline_engine.phase_executor.models import (
    PhaseStateSpec,
    build_phase_state_from_spec,
)
from agentkit.backend.pipeline_engine.runtime_state import EngineRuntimeState
from agentkit.backend.process.language.definitions import resolve_workflow
from agentkit.backend.state_backend.pipeline_runtime_store import save_phase_state
from agentkit.backend.state_backend.store.phase_envelope_repository import (
    StateBackendPhaseEnvelopeRepository,
)
from agentkit.backend.story_context_manager.story_model import WireStoryMode

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.pipeline_engine.lifecycle import PhaseHandlerRegistry
    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.backend.process.language.model import WorkflowDefinition
    from agentkit.backend.story_context_manager.models import StoryContext


@dataclass(frozen=True)
class PipelineRunResult:
    """Result of a complete pipeline run.

    Attributes:
        story_id: Identifier of the story that was executed.
        phases_executed: Ordered tuple of phase names that were entered.
        final_status: Terminal status -- one of ``"completed"``,
            ``"failed"``, ``"escalated"``, or ``"yielded"``.
        final_phase: Name of the last phase that was executed.
        errors: Error messages collected during the run.
        yielded: ``True`` if the pipeline yielded and needs a resume.
        yield_status: Descriptive yield reason (only when yielded).
        suggested_reaction: Typed escalation-reaction carrier propagated from
            the terminal :class:`EngineResult` (AG3-044 AC6, FK-26 §26.11.2).
            Set on a ``"failed"``/``"escalated"`` run when the
            handler recommended a concrete reaction (e.g. BLOCKED-manifest
            blocker details); ``None`` otherwise. Production callers read this
            structured payload instead of only the human-summary ``errors``.
    """

    story_id: str
    phases_executed: tuple[str, ...]
    final_status: str
    final_phase: str
    errors: tuple[str, ...] = ()
    yielded: bool = False
    yield_status: str | None = None
    suggested_reaction: str | None = None


def run_pipeline(
    story_context: StoryContext,
    story_dir: Path,
    handler_registry: PhaseHandlerRegistry,
    workflow: WorkflowDefinition | None = None,
) -> PipelineRunResult:
    """Run a story through the complete pipeline.

    This is the high-level orchestration function.  It:

    1. Resolves the workflow for the story type (or uses the provided one).
    2. Creates a :class:`PipelineEngine` and a :class:`PhaseEnvelopeStore`.
    3. Determines the starting phase (from existing state or first phase).
    4. Wraps state in a ``PhaseEnvelope`` (origin=LOADED or NEW) and
       runs phases sequentially, following transitions.
    5. Stops on: completion (no more transitions), yield, failure, or
       escalation.

    Args:
        story_context: The story to execute.
        story_dir: Directory for story artifacts and state.
        handler_registry: Registry of phase handlers.
        workflow: Optional workflow override.  If ``None``, resolved
            from the story type via
        :func:`~agentkit.backend.process.language.definitions.resolve_workflow`.

    Returns:
        A :class:`PipelineRunResult` summarising the execution.
    """
    resolved_workflow = workflow or resolve_workflow(story_context.story_type)
    engine = PipelineEngine(resolved_workflow, handler_registry, story_dir)
    envelope_store = PhaseEnvelopeStore(StateBackendPhaseEnvelopeRepository(story_dir))

    initial = _load_or_create_initial_envelope(
        story_context, story_dir, resolved_workflow, engine, envelope_store
    )
    if isinstance(initial, PipelineRunResult):
        return initial
    return _run_phase_loop(story_context, story_dir, engine, initial)


def _load_or_create_initial_envelope(
    story_context: StoryContext,
    story_dir: Path,
    resolved_workflow: WorkflowDefinition,
    engine: PipelineEngine,
    envelope_store: PhaseEnvelopeStore,
) -> PhaseEnvelope | PipelineRunResult:
    """Load an existing envelope or create a fresh one for the first phase.

    Returns a :class:`PipelineRunResult` on corrupt-state error, or a
    :class:`PhaseEnvelope` ready for the phase loop.
    """
    first_phase_name = resolved_workflow.phases[0].name
    try:
        first_phase = PhaseName(first_phase_name)
    except ValueError:
        first_phase = None

    try:
        envelope: PhaseEnvelope | None = (
            envelope_store.load(story_context.story_id, first_phase)
            if first_phase is not None
            else None
        )
    except CorruptStateError:
        return PipelineRunResult(
            story_id=story_context.story_id,
            phases_executed=(),
            final_status="failed",
            final_phase="",
            errors=(
                "Corrupt phase-state.json — cannot continue. "
                "Manual investigation required.",
            ),
        )

    if envelope is not None:
        return envelope

    now = datetime.now(tz=UTC)
    runtime = getattr(engine, "_runtime", None)
    run_id = (
        runtime.resolve_run_id(story_context)
        if isinstance(runtime, EngineRuntimeState)
        else EngineRuntimeState(resolved_workflow, story_dir).resolve_run_id(story_context)
    )
    fresh_state = build_phase_state_from_spec(
        PhaseStateSpec(
            story_id=story_context.story_id,
            run_id=run_id,
            phase=first_phase_name,
            status=PhaseStatus.PENDING,
            mode=phase_state_mode_from_context(
                execution_route=story_context.execution_route,
                fast=story_context.mode is WireStoryMode.FAST,
            ),
            story_type=story_context.story_type,
            attempt=1,
            started_at=now,
            phase_entered_at=now,
            producer=PhaseStateProducer(type="script", name="run-pipeline"),
        )
    )
    save_phase_state(story_dir, fresh_state)
    return PhaseEnvelopeStore.make_fresh_envelope(fresh_state)


def _run_phase_loop(
    story_context: StoryContext,
    story_dir: Path,
    engine: PipelineEngine,
    envelope: PhaseEnvelope,
) -> PipelineRunResult:
    """Drive the engine through sequential phases until a terminal result."""
    phases_executed: list[str] = []
    max_iterations = 20

    for _ in range(max_iterations):
        result = engine.run_phase(story_context, envelope)
        phases_executed.append(result.phase)
        if result.updated_context is not None:
            story_context = result.updated_context

        terminal = _check_terminal_result(story_context, result, phases_executed)
        if terminal is not None:
            return terminal

        # Advance to next phase (result.next_phase is not None here — checked in _check_terminal_result)
        now = datetime.now(tz=UTC)
        next_phase = result.next_phase
        assert next_phase is not None  # guaranteed by _check_terminal_result returning None
        next_state = build_phase_state_from_spec(
            PhaseStateSpec(
                story_id=story_context.story_id,
                run_id=envelope.state.run_id,
                phase=next_phase,
                status=PhaseStatus.PENDING,
                mode=envelope.state.mode,
                story_type=story_context.story_type,
                attempt=1,
                started_at=envelope.state.started_at,
                phase_entered_at=now,
                producer=PhaseStateProducer(type="script", name="run-pipeline"),
            )
        )
        save_phase_state(story_dir, next_state)
        envelope = PhaseEnvelopeStore.make_fresh_envelope(next_state)

    return PipelineRunResult(
        story_id=story_context.story_id,
        phases_executed=tuple(phases_executed),
        final_status="failed",
        final_phase=phases_executed[-1] if phases_executed else "",
        errors=("Max iteration limit reached",),
    )


def _check_terminal_result(
    story_context: StoryContext,
    result: EngineResult,
    phases_executed: list[str],
) -> PipelineRunResult | None:
    """Return a terminal PipelineRunResult for yield/fail/complete, or None to continue."""
    if result.status == "yielded":
        return PipelineRunResult(
            story_id=story_context.story_id,
            phases_executed=tuple(phases_executed),
            final_status="yielded",
            final_phase=result.phase,
            yielded=True,
            yield_status=result.yield_status,
        )

    if result.status in ("failed", "escalated"):
        return PipelineRunResult(
            story_id=story_context.story_id,
            phases_executed=tuple(phases_executed),
            final_status=result.status,
            final_phase=result.phase,
            errors=result.errors,
            # AG3-044 AC6 (FK-26 §26.11.2): forward typed escalation reaction.
            suggested_reaction=result.suggested_reaction,
        )

    if result.next_phase is None:
        return PipelineRunResult(
            story_id=story_context.story_id,
            phases_executed=tuple(phases_executed),
            final_status="completed",
            final_phase=result.phase,
        )

    return None
