"""High-level pipeline runner that orchestrates a complete story execution.

Provides :func:`run_pipeline`, a convenience function that drives a
:class:`~agentkit.pipeline_engine.engine.PipelineEngine` through all phases
of a workflow until completion, yield, failure, or escalation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.exceptions import CorruptStateError
from agentkit.pipeline_engine.engine import PipelineEngine
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.process.language.definitions import resolve_workflow
from agentkit.state_backend.store import save_phase_state
from agentkit.state_backend.store.phase_envelope_repository import (
    StateBackendPhaseEnvelopeRepository,
)
from agentkit.story_context_manager.models import PhaseName, PhaseState, PhaseStatus

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.pipeline_engine.lifecycle import PhaseHandlerRegistry
    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.process.language.model import WorkflowDefinition
    from agentkit.story_context_manager.models import StoryContext


@dataclass(frozen=True)
class PipelineRunResult:
    """Result of a complete pipeline run.

    Attributes:
        story_id: Identifier of the story that was executed.
        phases_executed: Ordered tuple of phase names that were entered.
        final_status: Terminal status -- one of ``"completed"``,
            ``"failed"``, ``"escalated"``, ``"blocked"``, or
            ``"yielded"``.
        final_phase: Name of the last phase that was executed.
        errors: Error messages collected during the run.
        yielded: ``True`` if the pipeline yielded and needs a resume.
        yield_status: Descriptive yield reason (only when yielded).
        suggested_reaction: Typed escalation-reaction carrier propagated from
            the terminal :class:`EngineResult` (AG3-044 AC6, FK-26 §26.11.2).
            Set on a ``"failed"``/``"escalated"``/``"blocked"`` run when the
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
        :func:`~agentkit.process.language.definitions.resolve_workflow`.

    Returns:
        A :class:`PipelineRunResult` summarising the execution.
    """
    # 1. Resolve workflow if not provided
    resolved_workflow = workflow or resolve_workflow(story_context.story_type)

    # 2. Create engine and envelope store
    engine = PipelineEngine(resolved_workflow, handler_registry, story_dir)
    repository = StateBackendPhaseEnvelopeRepository(story_dir)
    envelope_store = PhaseEnvelopeStore(repository)

    # 3. Load or create initial envelope (fail-closed on corrupt state)
    first_phase_name = resolved_workflow.phases[0].name
    # Attempt to derive a PhaseName from the workflow's first phase name
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

    if envelope is None:
        fresh_state = PhaseState(
            story_id=story_context.story_id,
            phase=first_phase_name,
            status=PhaseStatus.PENDING,
        )
        save_phase_state(story_dir, fresh_state)
        envelope = PhaseEnvelopeStore.make_fresh_envelope(fresh_state)

    # 4. Run phase loop
    phases_executed: list[str] = []
    max_iterations = 20  # safety limit

    for _ in range(max_iterations):
        result = engine.run_phase(story_context, envelope)
        phases_executed.append(result.phase)
        if result.updated_context is not None:
            story_context = result.updated_context

        if result.status == "yielded":
            return PipelineRunResult(
                story_id=story_context.story_id,
                phases_executed=tuple(phases_executed),
                final_status="yielded",
                final_phase=result.phase,
                yielded=True,
                yield_status=result.yield_status,
            )

        if result.status in ("failed", "escalated", "blocked"):
            return PipelineRunResult(
                story_id=story_context.story_id,
                phases_executed=tuple(phases_executed),
                final_status=result.status,
                final_phase=result.phase,
                errors=result.errors,
                # AG3-044 AC6 (FK-26 §26.11.2): forward the typed escalation
                # reaction end-to-end so the production caller gets the
                # structured blocker payload, not only the human-summary errors.
                suggested_reaction=result.suggested_reaction,
            )

        # phase_completed -- advance to next phase
        if result.next_phase is None:
            # Terminal phase reached -- pipeline complete
            return PipelineRunResult(
                story_id=story_context.story_id,
                phases_executed=tuple(phases_executed),
                final_status="completed",
                final_phase=result.phase,
            )

        # Create state for next phase and wrap in fresh envelope
        next_state = PhaseState(
            story_id=story_context.story_id,
            phase=result.next_phase,
            status=PhaseStatus.PENDING,
        )
        save_phase_state(story_dir, next_state)
        envelope = PhaseEnvelopeStore.make_fresh_envelope(next_state)

    # Safety limit reached
    return PipelineRunResult(
        story_id=story_context.story_id,
        phases_executed=tuple(phases_executed),
        final_status="failed",
        final_phase=phases_executed[-1] if phases_executed else "",
        errors=("Max iteration limit reached",),
    )
