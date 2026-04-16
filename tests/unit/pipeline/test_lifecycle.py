"""Tests for the phase handler protocol, registry, and NoOpHandler."""

from __future__ import annotations

import pytest

from agentkit.exceptions import PipelineError
from agentkit.pipeline.lifecycle import (
    HandlerResult,
    NoOpHandler,
    PhaseHandler,
    PhaseHandlerRegistry,
)
from agentkit.story_context_manager.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType


def _make_ctx() -> StoryContext:
    """Create a minimal StoryContext for testing."""
    return StoryContext(
        story_id="TEST-001",
        story_type=StoryType.IMPLEMENTATION,
        mode=StoryMode.EXPLORATION,
    )


def _make_state() -> PhaseState:
    """Create a minimal PhaseState for testing."""
    return PhaseState(
        story_id="TEST-001",
        phase="setup",
        status=PhaseStatus.PENDING,
    )


class TestHandlerResult:
    """Tests for HandlerResult construction and defaults."""

    def test_construction_with_all_fields(self) -> None:
        result = HandlerResult(
            status=PhaseStatus.COMPLETED,
            yield_status="awaiting_review",
            artifacts_produced=("protocol.md", "manifest.json"),
            errors=("some error",),
        )
        assert result.status == PhaseStatus.COMPLETED
        assert result.yield_status == "awaiting_review"
        assert result.artifacts_produced == ("protocol.md", "manifest.json")
        assert result.errors == ("some error",)

    def test_defaults(self) -> None:
        result = HandlerResult(status=PhaseStatus.FAILED)
        assert result.status == PhaseStatus.FAILED
        assert result.yield_status is None
        assert result.artifacts_produced == ()
        assert result.errors == ()

    def test_frozen(self) -> None:
        result = HandlerResult(status=PhaseStatus.COMPLETED)
        with pytest.raises(AttributeError):
            result.status = PhaseStatus.FAILED  # type: ignore[misc]


class TestNoOpHandler:
    """Tests for the NoOpHandler stub implementation."""

    def test_satisfies_phase_handler_protocol(self) -> None:
        handler = NoOpHandler()
        assert isinstance(handler, PhaseHandler)

    def test_on_enter_returns_completed(self) -> None:
        handler = NoOpHandler()
        result = handler.on_enter(_make_ctx(), _make_state())
        assert result.status == PhaseStatus.COMPLETED

    def test_on_exit_returns_none(self) -> None:
        handler = NoOpHandler()
        result = handler.on_exit(_make_ctx(), _make_state())
        assert result is None

    def test_on_resume_returns_completed(self) -> None:
        handler = NoOpHandler()
        result = handler.on_resume(_make_ctx(), _make_state(), "manual_trigger")
        assert result.status == PhaseStatus.COMPLETED


class TestPhaseHandlerRegistry:
    """Tests for PhaseHandlerRegistry registration and lookup."""

    def test_register_and_get_handler(self) -> None:
        registry = PhaseHandlerRegistry()
        handler = NoOpHandler()
        registry.register("setup", handler)
        assert registry.get_handler("setup") is handler

    def test_get_handler_unregistered_raises_pipeline_error(self) -> None:
        registry = PhaseHandlerRegistry()
        with pytest.raises(
            PipelineError,
            match="No handler registered for phase 'verify'",
        ):
            registry.get_handler("verify")

    def test_has_handler_registered(self) -> None:
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        assert registry.has_handler("setup") is True

    def test_has_handler_unregistered(self) -> None:
        registry = PhaseHandlerRegistry()
        assert registry.has_handler("setup") is False

    def test_registered_phases_empty(self) -> None:
        registry = PhaseHandlerRegistry()
        assert registry.registered_phases == frozenset()

    def test_registered_phases_multiple(self) -> None:
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        registry.register("verify", NoOpHandler())
        assert registry.registered_phases == frozenset({"setup", "verify"})

    def test_register_overwrites_existing(self) -> None:
        registry = PhaseHandlerRegistry()
        handler_a = NoOpHandler()
        handler_b = NoOpHandler()
        registry.register("setup", handler_a)
        registry.register("setup", handler_b)
        assert registry.get_handler("setup") is handler_b
