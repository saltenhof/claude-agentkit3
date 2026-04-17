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
    from agentkit.story_context_manager.models import PhaseState, StoryContext


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
    def PASS(cls) -> GuardResult:  # noqa: N802
        """Create a passing guard result.

        Returns:
            A ``GuardResult`` with ``passed=True``.
        """
        return cls(passed=True)

    @classmethod
    def FAIL(cls, *, reason: str) -> GuardResult:  # noqa: N802
        """Create a failing guard result with a reason.

        Args:
            reason: Human-readable explanation of why the guard failed.

        Returns:
            A ``GuardResult`` with ``passed=False`` and the given reason.
        """
        return cls(passed=False, reason=reason)


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
    from agentkit.story_context_manager.models import PhaseStatus

    if state.phase == "setup" and state.status == PhaseStatus.COMPLETED:
        return GuardResult.PASS()
    return GuardResult.FAIL(
        reason=f"Setup phase not completed: phase={state.phase!r}, "
        f"status={state.status!r}",
    )


@guard(
    "exploration_gate_approved",
    description="Checks that the exploration gate has been approved.",
    reads=frozenset({"phase", "status"}),
)
def exploration_gate_approved(
    ctx: StoryContext, state: PhaseState,
) -> GuardResult:
    """Check whether the exploration gate has been approved.

    Verifies that the exploration phase completed, indicating the
    design artifact has been reviewed and approved.

    Args:
        ctx: The story context (unused but required by signature).
        state: The current phase state to inspect.

    Returns:
        ``GuardResult.PASS()`` if exploration is completed, ``FAIL`` otherwise.
    """
    from agentkit.story_context_manager.models import PhaseStatus

    if state.phase == "exploration" and state.status == PhaseStatus.COMPLETED:
        return GuardResult.PASS()
    return GuardResult.FAIL(
        reason=f"Exploration gate not approved: phase={state.phase!r}, "
        f"status={state.status!r}",
    )


@guard(
    "verify_completed",
    description="Checks that the verify phase has completed successfully.",
    reads=frozenset({"phase", "status"}),
)
def verify_completed(ctx: StoryContext, state: PhaseState) -> GuardResult:
    """Check whether the verify phase completed successfully.

    Args:
        ctx: The story context (unused but required by signature).
        state: The current phase state to inspect.

    Returns:
        ``GuardResult.PASS()`` if verify is completed, ``FAIL`` otherwise.
    """
    from agentkit.story_context_manager.models import PhaseStatus

    if state.phase == "verify" and state.status == PhaseStatus.COMPLETED:
        return GuardResult.PASS()
    return GuardResult.FAIL(
        reason=f"Verify phase not completed: phase={state.phase!r}, "
        f"status={state.status!r}",
    )


@guard(
    "verify_needs_remediation",
    description="Checks that verify phase did NOT complete successfully.",
    reads=frozenset({"phase", "status"}),
)
def verify_needs_remediation(
    ctx: StoryContext, state: PhaseState,
) -> GuardResult:
    """Check whether the verify phase needs remediation.

    This guard passes when the verify phase did NOT complete successfully,
    indicating that remediation is needed. It prevents the remediation
    transition from firing when verify actually passed.

    Args:
        ctx: The story context (unused but required by signature).
        state: The current phase state to inspect.

    Returns:
        ``GuardResult.PASS()`` if verify is not completed (remediation needed),
        ``GuardResult.FAIL`` if verify completed successfully.
    """
    from agentkit.story_context_manager.models import PhaseStatus

    if state.phase == "verify" and state.status != PhaseStatus.COMPLETED:
        return GuardResult.PASS()
    return GuardResult.FAIL(
        reason="Verify phase completed successfully, no remediation needed",
    )


@guard(
    "mode_is_exploration",
    description="Checks that the story mode is EXPLORATION.",
    reads=frozenset({"mode"}),
)
def mode_is_exploration(ctx: StoryContext, state: PhaseState) -> GuardResult:
    """Check whether the story is running in exploration mode.

    Args:
        ctx: The story context to inspect for mode.
        state: The current phase state (unused but required by signature).

    Returns:
        ``GuardResult.PASS()`` if mode is EXPLORATION, ``FAIL`` otherwise.
    """
    from agentkit.story_context_manager.types import StoryMode

    if ctx.mode == StoryMode.EXPLORATION:
        return GuardResult.PASS()
    return GuardResult.FAIL(
        reason=f"Story mode is not EXPLORATION: mode={ctx.mode!r}",
    )
