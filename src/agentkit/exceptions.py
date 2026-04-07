"""AgentKit exception hierarchy.

All AgentKit-specific exceptions inherit from :class:`AgentKitError`.
Each exception carries an optional ``detail`` dict for structured error
information that callers can inspect programmatically.
"""

from __future__ import annotations

from typing import Any


class AgentKitError(Exception):
    """Base exception for all AgentKit errors.

    Args:
        message: Human-readable error description.
        detail: Optional structured error information.
    """

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail: dict[str, Any] = detail or {}


class ConfigError(AgentKitError):
    """Configuration loading or validation failure.

    Raised when a configuration file is missing, contains invalid YAML,
    or fails Pydantic validation.
    """


class StoryError(AgentKitError):
    """Story domain error.

    Raised for invalid story metadata, unsupported story types,
    or story lifecycle violations.
    """


class PipelineError(AgentKitError):
    """Pipeline orchestration error.

    Raised when the 5-phase pipeline encounters an unrecoverable
    condition during phase execution or phase transitions.
    """


class WorkflowError(AgentKitError):
    """Workflow DSL or state machine error.

    Raised for workflow definition problems or runtime state machine
    violations.
    """


class TransitionError(WorkflowError):
    """Invalid state transition.

    Raised when a requested state transition is not allowed by the
    workflow definition (e.g. skipping a mandatory phase).
    """


class GuardError(WorkflowError):
    """Guard evaluation failure.

    Raised when a guard condition on a workflow transition evaluates
    to ``False``, blocking the transition.
    """


class GateError(WorkflowError):
    """Gate evaluation failure.

    Raised when a quality gate check fails, preventing progression
    to the next pipeline phase.
    """


class PreconditionError(PipelineError):
    """Phase precondition not met.

    Raised when a pipeline phase cannot start because its required
    preconditions (artifacts, state, configuration) are not satisfied.
    """


class ProjectError(AgentKitError):
    """Project model or discovery error.

    Raised when a target project cannot be found, its structure is
    invalid, or its configuration directory is missing.
    """


class IntegrationError(AgentKitError):
    """External integration error.

    Raised when communication with an external system (GitHub, VectorDB,
    LLM pools, MCP servers) fails or returns unexpected results.
    """


class GovernanceError(AgentKitError):
    """Governance violation.

    Raised when an operation violates governance policies such as
    trust-class restrictions, policy-engine rules, or audit requirements.
    """


class ArtifactError(AgentKitError):
    """Missing or corrupt artifact.

    Raised when a required artifact (protocol.md, manifest, handover,
    QA reports) is missing, incomplete, or fails integrity checks.
    """
