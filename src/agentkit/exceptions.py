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


class CorruptStateError(PipelineError):
    """Raised when phase-state.json exists but is corrupt or invalid.

    This indicates a file-system-level corruption (invalid JSON, wrong
    schema, non-dict content) rather than a missing file (which is a
    normal "fresh run" condition).  The pipeline MUST fail-closed on
    corrupt state instead of silently restarting from scratch.
    """


class PreconditionError(PipelineError):
    """Phase precondition not met.

    Raised when a pipeline phase cannot start because its required
    preconditions (artifacts, state, configuration) are not satisfied.
    """


class ControlPlaneClaimCollisionError(AgentKitError):
    """A non-owner control-plane save collided with a LIVE ``claimed`` lease.

    AG3-054 ERROR-3: raised when the legacy control-plane operation upsert would
    have overwritten a row that is still ``claimed`` (a live, owned lease). Only
    the owner's ownership-scoped finalize/release may transition a claimed row, so
    a ``complete_phase`` / ``fail_phase`` (or any non-owner save) reusing a live
    ``start_phase`` op_id must NOT clobber and steal/destroy its ownership. The
    runtime surfaces this fail-closed as a ``rejected`` mutation result.
    """


class ControlPlaneBindingCollisionError(AgentKitError):
    """A control-plane binding write/delete collided with a FOREIGN run's binding.

    AG3-054 (run-scoping sweep): the session-run-binding is keyed by ``session_id``
    (one row per session) but carries ``(project_key, story_id, run_id)``. A
    control-plane side-effect that creates/overwrites or deletes "the binding for
    this session" must NEVER touch a live binding that belongs to a DIFFERENT run
    which has since rebound the same ``session_id``. When a binding SAVE
    (start finalize / complete / fail) would overwrite, or a binding DELETE
    (closure teardown) would remove, a binding whose ``(project_key, story_id,
    run_id)`` does not match the operating run, the store refuses fail-closed and
    raises this error so the WHOLE atomic transaction rolls back (no foreign
    binding clobber, no orphan teardown). The runtime surfaces it as a ``rejected``
    mutation result, mirroring :class:`ControlPlaneClaimCollisionError`.
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


class WorktreeError(AgentKitError):
    """Git worktree operation failure.

    Raised when creating or removing a git worktree fails, e.g. because
    the target path already exists, the git command returns a non-zero
    exit code, or the repository is in an unexpected state.
    """


class InstallationError(ProjectError):
    """Target-project installation failure (installer/bootstrap BC, FK-50).

    Raised when ``install_agentkit`` cannot complete a fail-closed step, e.g.
    a mandatory skill bundle is not available in the systemwide bundle store
    (``detail["cause"] == "BundleNotFound"``). FAIL-CLOSED: the installer must
    abort before creating any partial install artifact (no partial symlinks).
    """
