"""Guard system for workflow transitions.

Guards are side-effect-free callables that evaluate whether a transition
or phase entry is allowed. They return a ``GuardResult`` indicating
PASS or FAIL with an optional reason.

The ``@guard`` decorator binds metadata (name, description, reads)
to guard functions for introspection and documentation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.pipeline_engine.phase_executor import PhaseState
    from agentkit.story_context_manager.models import StoryContext


@dataclass(frozen=True)
class GuardResult:
    """Result of a guard evaluation.

    Args:
        passed: Whether the guard condition is satisfied.
        reason: Human-readable explanation (typically set on failure).
    """

    passed: bool
    reason: str | None = None

    @classmethod
    def pass_(cls) -> GuardResult:
        """Create a passing guard result.

        Returns:
            A ``GuardResult`` with ``passed=True``.
        """
        return cls(passed=True)

    @classmethod
    def fail(cls, *, reason: str) -> GuardResult:
        """Create a failing guard result with a reason.

        Args:
            reason: Human-readable explanation of why the guard failed.

        Returns:
            A ``GuardResult`` with ``passed=False`` and the given reason.
        """
        return cls(passed=False, reason=reason)

    PASS = pass_  # NOSONAR - public DSL compatibility alias
    FAIL = fail  # NOSONAR - public DSL compatibility alias


GuardFn = Callable[["StoryContext", "PhaseState"], GuardResult]
"""Type alias for guard function signature.

A guard function takes a ``StoryContext`` and ``PhaseState`` and returns
a ``GuardResult``. Guards MUST be side-effect-free.
"""


def guard(
    name: str,
    *,
    description: str = "",
    reads: frozenset[str] | None = None,
) -> Callable[[GuardFn], GuardFn]:
    """Decorator that binds metadata to a guard function.

    The decorated function retains its original callable behavior but
    gains ``guard_name``, ``guard_description``, and ``guard_reads``
    attributes for introspection.

    Args:
        name: Short identifier for the guard.
        description: Human-readable description of what the guard checks.
        reads: Optional set of field names the guard reads from context.

    Returns:
        A decorator that attaches metadata to the guard function.
    """

    def decorator(fn: GuardFn) -> GuardFn:
        # Attach metadata directly on the function object
        fn.guard_name = name  # type: ignore[attr-defined]
        fn.guard_description = description  # type: ignore[attr-defined]
        fn.guard_reads = reads or frozenset()  # type: ignore[attr-defined]
        return fn

    return decorator


@guard(
    "preflight_passed",
    description="Checks that the setup phase has completed successfully.",
    reads=frozenset({"phase", "status"}),
)
def preflight_passed(ctx: StoryContext, state: PhaseState) -> GuardResult:
    """Check whether the setup phase completed successfully.

    This guard verifies that the pipeline has passed through the setup
    phase with a COMPLETED status before allowing transition to the
    next phase.

    Args:
        ctx: The story context (unused but required by signature).
        state: The current phase state to inspect.

    Returns:
        ``GuardResult.PASS()`` if setup is completed, ``FAIL`` otherwise.
    """
    from agentkit.pipeline_engine.phase_executor import PhaseStatus

    if state.phase == "setup" and state.status == PhaseStatus.COMPLETED:
        return GuardResult.PASS()
    return GuardResult.FAIL(
        reason=f"Setup phase not completed: phase={state.phase!r}, "
        f"status={state.status!r}",
    )


@guard(
    "exploration_gate_approved",
    description="Checks that the exploration gate has been approved.",
    reads=frozenset({"phase", "status", "payload"}),
)
def exploration_gate_approved(
    ctx: StoryContext, state: PhaseState,
) -> GuardResult:
    """Check whether the exploration gate has been approved.

    Defense-in-Depth (FK-23 §23.5.0 / FK-45 §45.2): the exploration phase
    being ``COMPLETED`` is NOT sufficient to enter implementation. The
    persisted :class:`ExplorationPayload` MUST additionally carry
    ``gate_status == ExplorationGateStatus.APPROVED``. A phase that is
    ``COMPLETED`` for any other reason — or whose gate is still ``PENDING`` /
    ``REJECTED``, or whose payload is missing / of the wrong type — fails the
    guard fail-closed and does not release the Implementation phase.

    Args:
        ctx: The story context (unused but required by signature).
        state: The current phase state to inspect.

    Returns:
        ``GuardResult.PASS()`` only when phase is ``exploration``, status is
        ``COMPLETED`` AND ``payload.gate_status == APPROVED``; ``FAIL``
        otherwise.
    """
    from agentkit.core_types import ExplorationGateStatus
    from agentkit.pipeline_engine.phase_executor import (
        ExplorationPayload,
        PhaseName,
        PhaseStatus,
    )

    payload = state.payload
    approved = (
        state.phase == PhaseName.EXPLORATION
        and state.status == PhaseStatus.COMPLETED
        and isinstance(payload, ExplorationPayload)
        and payload.gate_status == ExplorationGateStatus.APPROVED
    )
    if approved:
        return GuardResult.PASS()
    gate_status = getattr(payload, "gate_status", None)
    return GuardResult.FAIL(
        reason=(
            "Exploration gate not approved: "
            f"phase={state.phase!r}, status={state.status!r}, "
            f"gate_status={gate_status!r}"
        ),
    )


@guard(
    "implementation_completed",
    description="Checks that implementation completed including QA-subflow.",
    reads=frozenset({"phase", "status"}),
)
def implementation_completed(ctx: StoryContext, state: PhaseState) -> GuardResult:
    """Check whether implementation completed successfully.

    Args:
        ctx: The story context (unused but required by signature).
        state: The current phase state to inspect.

    Returns:
        ``GuardResult.PASS()`` if implementation is completed, ``FAIL`` otherwise.
    """
    from agentkit.pipeline_engine.phase_executor import PhaseStatus

    if state.phase == "implementation" and state.status == PhaseStatus.COMPLETED:
        return GuardResult.PASS()
    return GuardResult.FAIL(
        reason=f"Implementation phase not completed: phase={state.phase!r}, "
        f"status={state.status!r}",
    )


@guard(
    "implementation_qa_needs_remediation",
    description="Checks that implementation QA-subflow needs remediation.",
    reads=frozenset({"phase", "status"}),
)
def implementation_qa_needs_remediation(
    ctx: StoryContext, state: PhaseState,
) -> GuardResult:
    """Check whether the implementation QA-subflow needs remediation.

    This guard passes when implementation did NOT complete successfully,
    indicating that remediation is needed. It prevents the remediation
    transition from firing when verify actually passed.

    Args:
        ctx: The story context (unused but required by signature).
        state: The current phase state to inspect.

    Returns:
        ``GuardResult.PASS()`` if implementation needs remediation,
        ``GuardResult.FAIL`` if implementation completed successfully.
    """
    from agentkit.pipeline_engine.phase_executor import PhaseStatus

    if state.phase == "implementation" and state.status != PhaseStatus.COMPLETED:
        return GuardResult.PASS()
    return GuardResult.FAIL(
        reason="Implementation phase completed successfully, no remediation needed",
    )


@guard(
    "mode_is_exploration",
    description="Checks that the story execution route is EXPLORATION.",
    reads=frozenset({"execution_route"}),
)
def mode_is_exploration(ctx: StoryContext, state: PhaseState) -> GuardResult:
    """Check whether the story is running on the exploration route.

    Fast-mode override (AG3-018, FK-24 §24.3.4 Mode-Profil ``Exploration =
    OUT``): a ``mode == fast`` story NEVER enters the Exploration phase, even
    when its ``execution_route`` would otherwise route there. The fast/standard
    ``mode`` axis is decoupled from ``execution_route`` (FK-24 §24.3.3); this
    guard fails closed for fast so the ``setup -> implementation`` transition
    wins and Setup routes directly to Implementation.

    Args:
        ctx: The story context to inspect for execution route + mode.
        state: The current phase state (unused but required by signature).

    Returns:
        ``GuardResult.PASS()`` only when the route is EXPLORATION AND the story
        is not in fast mode; ``FAIL`` otherwise.
    """
    from agentkit.story_context_manager.story_model import WireStoryMode
    from agentkit.story_context_manager.types import StoryMode

    if ctx.mode is WireStoryMode.FAST:
        return GuardResult.FAIL(
            reason=(
                "Story is in fast mode: the Exploration phase is skipped "
                "(FK-24 §24.3.4 Mode-Profil Exploration=OUT); routing setup "
                "directly to implementation"
            ),
        )
    if ctx.execution_route == StoryMode.EXPLORATION:
        return GuardResult.PASS()
    return GuardResult.FAIL(
        reason=(
            "Story execution route is not EXPLORATION: "
            f"execution_route={ctx.execution_route!r}"
        ),
    )
