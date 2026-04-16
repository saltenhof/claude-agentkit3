"""Phase handler protocol and registry for pipeline phase implementations.

Defines the ``PhaseHandler`` protocol that all pipeline phase handlers
must satisfy, a ``HandlerResult`` value object describing handler outcomes,
a ``NoOpHandler`` for testing, and a ``PhaseHandlerRegistry`` for mapping
phase names to their handler implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.exceptions import PipelineError
from agentkit.story_context_manager.models import PhaseStatus

if TYPE_CHECKING:
    from agentkit.story_context_manager.models import PhaseState, StoryContext


@dataclass(frozen=True)
class HandlerResult:
    """Result returned by a phase handler.

    Tells the engine what happened and what to do next.

    Args:
        status: Final phase status after handler execution.
        yield_status: Descriptive yield reason if status is PAUSED
            (e.g. ``"awaiting_design_review"``).
        artifacts_produced: Paths to artifacts produced during execution.
        errors: Error messages if the phase FAILED.
    """

    status: PhaseStatus
    yield_status: str | None = None
    artifacts_produced: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@runtime_checkable
class PhaseHandler(Protocol):
    """Protocol for phase handler implementations.

    Each pipeline phase (setup, exploration, implementation, verify, closure)
    has a handler that implements this protocol. The handler contains the
    execution logic -- the workflow DSL only defines topology.
    """

    def on_enter(self, ctx: StoryContext, state: PhaseState) -> HandlerResult:
        """Called when entering a phase. Do the main work here.

        Args:
            ctx: The story context for this pipeline run.
            state: The current phase state.

        Returns:
            A ``HandlerResult`` describing the outcome.
        """
        ...

    def on_exit(self, ctx: StoryContext, state: PhaseState) -> None:
        """Called when leaving a phase. Write snapshots, validate artifacts.

        Args:
            ctx: The story context for this pipeline run.
            state: The current phase state.
        """
        ...

    def on_resume(
        self, ctx: StoryContext, state: PhaseState, trigger: str,
    ) -> HandlerResult:
        """Called when resuming a yielded phase after external input.

        Args:
            ctx: The story context for this pipeline run.
            state: The current phase state.
            trigger: The resume trigger that caused re-entry.

        Returns:
            A ``HandlerResult`` describing the outcome.
        """
        ...


class NoOpHandler:
    """Default handler that immediately completes.

    Used for testing and as a stub when no real handler is available.
    Satisfies the ``PhaseHandler`` protocol.
    """

    def on_enter(self, ctx: StoryContext, state: PhaseState) -> HandlerResult:
        """Immediately return COMPLETED status.

        Args:
            ctx: The story context (unused).
            state: The current phase state (unused).

        Returns:
            A ``HandlerResult`` with ``COMPLETED`` status.
        """
        return HandlerResult(status=PhaseStatus.COMPLETED)

    def on_exit(self, ctx: StoryContext, state: PhaseState) -> None:
        """No-op exit -- does nothing.

        Args:
            ctx: The story context (unused).
            state: The current phase state (unused).
        """

    def on_resume(
        self, ctx: StoryContext, state: PhaseState, trigger: str,
    ) -> HandlerResult:
        """Immediately return COMPLETED status on resume.

        Args:
            ctx: The story context (unused).
            state: The current phase state (unused).
            trigger: The resume trigger (unused).

        Returns:
            A ``HandlerResult`` with ``COMPLETED`` status.
        """
        return HandlerResult(status=PhaseStatus.COMPLETED)


class PhaseHandlerRegistry:
    """Registry mapping phase names to their handler implementations.

    Provides registration, lookup, and introspection of phase handlers.
    Each phase name can have at most one handler registered.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, PhaseHandler] = {}

    def register(self, phase_name: str, handler: PhaseHandler) -> None:
        """Register a handler for a phase.

        Args:
            phase_name: The name of the phase (e.g. ``"setup"``).
            handler: The handler implementing the ``PhaseHandler`` protocol.
        """
        self._handlers[phase_name] = handler

    def get_handler(self, phase_name: str) -> PhaseHandler:
        """Get the handler for a phase.

        Args:
            phase_name: The name of the phase to look up.

        Returns:
            The registered ``PhaseHandler``.

        Raises:
            PipelineError: If no handler is registered for the given phase.
        """
        if phase_name not in self._handlers:
            raise PipelineError(
                f"No handler registered for phase '{phase_name}'",
            )
        return self._handlers[phase_name]

    def has_handler(self, phase_name: str) -> bool:
        """Check if a handler is registered for a phase.

        Args:
            phase_name: The phase name to check.

        Returns:
            ``True`` if a handler is registered, ``False`` otherwise.
        """
        return phase_name in self._handlers

    @property
    def registered_phases(self) -> frozenset[str]:
        """Return the set of phase names with registered handlers.

        Returns:
            A frozen set of registered phase name strings.
        """
        return frozenset(self._handlers.keys())
