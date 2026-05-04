"""Domain exceptions for execution_planning."""

from __future__ import annotations

from agentkit.exceptions import AgentKitError


class StoryDependencyCycleError(AgentKitError):
    """Raised when a dependency edge would create a cycle."""

    def __init__(self, message: str, *, path: list[str]) -> None:
        super().__init__(message, detail={"path": path})
        self.path = path


class StoryDependencyNotFoundError(AgentKitError):
    """Raised when a dependency edge or story dependency endpoint is missing."""


class StoryDependencyConflictError(AgentKitError):
    """Raised when a dependency edge conflicts with existing graph state."""


class ParallelizationConfigError(AgentKitError):
    """Raised when parallelization configuration is invalid."""
