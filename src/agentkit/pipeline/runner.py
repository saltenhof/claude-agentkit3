"""High-level pipeline runner that orchestrates a complete story execution.

Provides :func:`run_pipeline`, a convenience function that drives a
:class:`~agentkit.pipeline.engine.PipelineEngine` through all phases
of a workflow until completion, yield, failure, or escalation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.pipeline.engine import PipelineEngine
from agentkit.pipeline.state import load_phase_state, save_phase_state
from agentkit.pipeline.workflow.definitions import resolve_workflow
from agentkit.story.models import PhaseState, PhaseStatus

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.pipeline.lifecycle import PhaseHandlerRegistry
    from agentkit.pipeline.workflow.model import WorkflowDefinition
    from agentkit.story.models import StoryContext


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
    """

    story_id: str
    phases_executed: tuple[str, ...]
    final_status: str
    final_phase: str
    errors: tuple[str, ...] = ()
    yielded: bool = False
    yield_status: str | None = None


def run_pipeline(
    story_context: StoryContext,
    story_dir: Path,
    handler_registry: PhaseHandlerRegistry,
    workflow: WorkflowDefinition | None = None,
) -> PipelineRunResult:
    """Run a story through the complete pipeline.

    This is the high-level orchestration function.  It:

    1. Resolves the workflow for the story type (or uses the provided one).
    2. Creates a :class:`PipelineEngine`.
    3. Determines the starting phase (from existing state or first phase).
    4. Runs phases sequentially, following transitions.
    5. Stops on: completion (no more transitions), yield, failure, or
       escalation.

    Args:
        story_context: The story to execute.
        story_dir: Directory for story artifacts and state.
        handler_registry: Registry of phase handlers.
        workflow: Optional workflow override.  If ``None``, resolved
            from the story type via
            :func:`~agentkit.pipeline.workflow.definitions.resolve_workflow`.

    Returns:
        A :class:`PipelineRunResult` summarising the execution.
    """
    # 1. Resolve workflow if not provided
    resolved_workflow = workflow or resolve_workflow(story_context.story_type)

    # 2. Create engine
    engine = PipelineEngine(resolved_workflow, handler_registry, story_dir)

    # 3. Load or create initial state
    state = load_phase_state(story_dir)
    if state is None:
        first_phase = resolved_workflow.phases[0].name
        state = PhaseState(
            story_id=story_context.story_id,
            phase=first_phase,
            status=PhaseStatus.PENDING,
        )
        save_phase_state(story_dir, state)

    # 4. Run phase loop
    phases_executed: list[str] = []
    max_iterations = 20  # safety limit

    for _ in range(max_iterations):
        result = engine.run_phase(story_context, state)
        phases_executed.append(result.phase)

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

        # Create state for next phase
        state = PhaseState(
            story_id=story_context.story_id,
            phase=result.next_phase,
            status=PhaseStatus.PENDING,
        )
        save_phase_state(story_dir, state)

    # Safety limit reached
    return PipelineRunResult(
        story_id=story_context.story_id,
        phases_executed=tuple(phases_executed),
        final_status="failed",
        final_phase=phases_executed[-1] if phases_executed else "",
        errors=("Max iteration limit reached",),
    )
