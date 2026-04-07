"""Unit tests for agentkit.exceptions."""

from __future__ import annotations

import pytest

from agentkit.exceptions import (
    AgentKitError,
    ArtifactError,
    ConfigError,
    GateError,
    GovernanceError,
    GuardError,
    IntegrationError,
    PipelineError,
    PreconditionError,
    ProjectError,
    StoryError,
    TransitionError,
    WorkflowError,
)


class TestAgentKitError:
    """Tests for the base AgentKitError."""

    def test_message_stored(self) -> None:
        err = AgentKitError("something went wrong")
        assert str(err) == "something went wrong"

    def test_detail_defaults_to_empty_dict(self) -> None:
        err = AgentKitError("msg")
        assert err.detail == {}

    def test_detail_stored(self) -> None:
        detail = {"file": "config.yaml", "line": 42}
        err = AgentKitError("msg", detail=detail)
        assert err.detail == detail

    def test_is_exception(self) -> None:
        assert issubclass(AgentKitError, Exception)


class TestExceptionHierarchy:
    """Verify that every exception inherits from the correct parent."""

    @pytest.mark.parametrize(
        ("cls", "parent"),
        [
            (ConfigError, AgentKitError),
            (StoryError, AgentKitError),
            (PipelineError, AgentKitError),
            (WorkflowError, AgentKitError),
            (TransitionError, WorkflowError),
            (GuardError, WorkflowError),
            (GateError, WorkflowError),
            (PreconditionError, PipelineError),
            (ProjectError, AgentKitError),
            (IntegrationError, AgentKitError),
            (GovernanceError, AgentKitError),
            (ArtifactError, AgentKitError),
        ],
    )
    def test_subclass(
        self, cls: type[AgentKitError], parent: type[Exception]
    ) -> None:
        assert issubclass(cls, parent)

    def test_transition_error_is_also_agentkit_error(self) -> None:
        assert issubclass(TransitionError, AgentKitError)

    def test_precondition_error_is_also_agentkit_error(self) -> None:
        assert issubclass(PreconditionError, AgentKitError)


class TestExceptionDetail:
    """All exception subclasses support the detail kwarg."""

    @pytest.mark.parametrize(
        "cls",
        [
            ConfigError,
            StoryError,
            PipelineError,
            WorkflowError,
            TransitionError,
            GuardError,
            GateError,
            PreconditionError,
            ProjectError,
            IntegrationError,
            GovernanceError,
            ArtifactError,
        ],
    )
    def test_detail_kwarg(self, cls: type[AgentKitError]) -> None:
        detail = {"reason": "test"}
        err = cls("test message", detail=detail)
        assert err.detail == detail
        assert str(err) == "test message"

    @pytest.mark.parametrize(
        "cls",
        [
            ConfigError,
            StoryError,
            PipelineError,
            WorkflowError,
            TransitionError,
            GuardError,
            GateError,
            PreconditionError,
            ProjectError,
            IntegrationError,
            GovernanceError,
            ArtifactError,
        ],
    )
    def test_catchable_as_agentkit_error(self, cls: type[AgentKitError]) -> None:
        with pytest.raises(AgentKitError):
            raise cls("test")
