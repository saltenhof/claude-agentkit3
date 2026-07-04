"""Unit tests for agentkit.backend.exceptions."""

from __future__ import annotations

import pytest

from agentkit.backend.exceptions import (
    AgentKitError,
    ArtifactError,
    ConfigError,
    ControlPlaneApiError,
    ControlPlaneBindingCollisionError,
    ControlPlaneClaimCollisionError,
    GateError,
    GovernanceError,
    GuardError,
    IntegrationError,
    OwnershipFenceViolationError,
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


class TestControlPlaneApiError:
    """Regression pin (AG3-142 collision post-mortem): a prior uncoordinated
    edit deleted this class's ``class`` declaration while keeping its
    docstring/``__init__`` body, silently breaking ~15 importers (CLI,
    ``harness_client.projectedge.client``, the target-project bundle tool,
    and 8+ test files) with an ``ImportError`` that no test caught. This
    class carries a NON-standard ``__init__`` (``error_code`` /
    ``correlation_id`` / ``http_status``, distinct from the base
    ``AgentKitError(message, detail=)`` shape), so a generic
    ``TestExceptionHierarchy``-style parametrization would not have caught a
    silent deletion either -- it needs its OWN dedicated pin.
    """

    def test_importable_from_exceptions_module(self) -> None:
        import agentkit.backend.exceptions as exceptions_module

        assert exceptions_module.ControlPlaneApiError is ControlPlaneApiError

    def test_is_agentkit_error(self) -> None:
        assert issubclass(ControlPlaneApiError, AgentKitError)

    def test_constructs_with_its_own_required_kwargs(self) -> None:
        err = ControlPlaneApiError(
            "boundary rejected the request",
            error_code="reconciliation_evidence_missing",
            correlation_id="corr-1",
            http_status=422,
            detail={"field": "reconciliation"},
        )

        assert str(err) == "boundary rejected the request"
        assert err.error_code == "reconciliation_evidence_missing"
        assert err.correlation_id == "corr-1"
        assert err.http_status == 422
        assert err.detail == {"field": "reconciliation"}

    def test_catchable_as_agentkit_error(self) -> None:
        with pytest.raises(AgentKitError):
            raise ControlPlaneApiError(
                "x", error_code="e", correlation_id="c", http_status=409
            )


class TestOwnershipFenceViolationError:
    """AG3-142: the commit-time ownership-fence violation signal (FK-56 §56.8a).

    Raised by the state-backend row functions inside the SAME transaction as
    the claim-CAS finalize / collision-gated commit; the runtime catches it
    and builds the ``ownership_transferred`` ex-owner rejection.
    """

    def test_is_agentkit_error(self) -> None:
        assert issubclass(OwnershipFenceViolationError, AgentKitError)

    def test_carries_structured_detail(self) -> None:
        err = OwnershipFenceViolationError(
            "ownership fence violated",
            detail={
                "current_owner_session_id": "sess-new",
                "current_ownership_epoch": 2,
                "transferred_at": "2026-07-04T00:00:00+00:00",
            },
        )

        assert err.detail["current_owner_session_id"] == "sess-new"
        assert err.detail["current_ownership_epoch"] == 2

    def test_catchable_as_agentkit_error(self) -> None:
        with pytest.raises(AgentKitError):
            raise OwnershipFenceViolationError("x", detail={})


class TestControlPlaneCollisionErrorsStillImportable:
    """Adjacent regression pin: the SAME AG3-142 collision touched this module
    around ``ControlPlaneClaimCollisionError`` / ``ControlPlaneBindingCollisionError``
    too (AG3-054 pre-existing classes, immediately above the corrupted
    section) -- pin their importability alongside the corrupted class so a
    future edit in this neighbourhood cannot silently drop them either.
    """

    @pytest.mark.parametrize(
        "cls",
        [ControlPlaneClaimCollisionError, ControlPlaneBindingCollisionError],
    )
    def test_importable_and_is_agentkit_error(self, cls: type[AgentKitError]) -> None:
        assert issubclass(cls, AgentKitError)
        with pytest.raises(AgentKitError):
            raise cls("test")
