"""Unit tests for agentkit.story.models."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.types import StoryMode, StoryType


class TestPhaseStatus:
    """Tests for the PhaseStatus enum."""

    def test_all_values(self) -> None:
        assert set(PhaseStatus) == {
            PhaseStatus.PENDING,
            PhaseStatus.IN_PROGRESS,
            PhaseStatus.PAUSED,
            PhaseStatus.COMPLETED,
            PhaseStatus.FAILED,
            PhaseStatus.ESCALATED,
            PhaseStatus.BLOCKED,
        }

    def test_string_values(self) -> None:
        assert PhaseStatus.PENDING == "pending"
        assert PhaseStatus.IN_PROGRESS == "in_progress"
        assert PhaseStatus.PAUSED == "paused"
        assert PhaseStatus.COMPLETED == "completed"
        assert PhaseStatus.FAILED == "failed"
        assert PhaseStatus.ESCALATED == "escalated"
        assert PhaseStatus.BLOCKED == "blocked"


class TestStoryContext:
    """Tests for the StoryContext model."""

    def test_minimal_creation(self) -> None:
        ctx = StoryContext(
            story_id="AG3-001",
            story_type=StoryType.IMPLEMENTATION,
            mode=StoryMode.EXPLORATION,
        )
        assert ctx.story_id == "AG3-001"
        assert ctx.story_type == StoryType.IMPLEMENTATION
        assert ctx.mode == StoryMode.EXPLORATION
        assert ctx.issue_nr is None
        assert ctx.title == ""
        assert ctx.project_root is None
        assert ctx.worktree_path is None
        assert ctx.participating_repos == []
        assert ctx.labels == []
        assert ctx.created_at is None

    def test_full_creation(self) -> None:
        now = datetime.now(tz=UTC)
        ctx = StoryContext(
            story_id="AG3-042",
            story_type=StoryType.BUGFIX,
            mode=StoryMode.EXECUTION,
            issue_nr=42,
            title="Fix null pointer in setup phase",
            project_root=Path("/tmp/project"),
            worktree_path=Path("/tmp/worktrees/AG3-042"),
            participating_repos=["saltenhof/claude-agentkit3"],
            labels=["bugfix", "size:small"],
            created_at=now,
        )
        assert ctx.issue_nr == 42
        assert ctx.title == "Fix null pointer in setup phase"
        assert ctx.project_root == Path("/tmp/project")
        assert ctx.worktree_path == Path("/tmp/worktrees/AG3-042")
        assert ctx.participating_repos == ["saltenhof/claude-agentkit3"]
        assert ctx.labels == ["bugfix", "size:small"]
        assert ctx.created_at == now

    def test_frozen_model(self) -> None:
        ctx = StoryContext(
            story_id="AG3-001",
            story_type=StoryType.IMPLEMENTATION,
            mode=StoryMode.EXPLORATION,
        )
        with pytest.raises(ValidationError):
            ctx.story_id = "AG3-002"  # type: ignore[misc]

    def test_requires_story_id(self) -> None:
        with pytest.raises(ValidationError):
            StoryContext(
                story_type=StoryType.IMPLEMENTATION,  # type: ignore[call-arg]
                mode=StoryMode.EXPLORATION,
            )

    def test_requires_story_type(self) -> None:
        with pytest.raises(ValidationError):
            StoryContext(
                story_id="AG3-001",  # type: ignore[call-arg]
                mode=StoryMode.EXPLORATION,
            )

    def test_requires_mode(self) -> None:
        with pytest.raises(ValidationError):
            StoryContext(
                story_id="AG3-001",  # type: ignore[call-arg]
                story_type=StoryType.IMPLEMENTATION,
            )

    def test_serialization_roundtrip(self) -> None:
        now = datetime.now(tz=UTC)
        ctx = StoryContext(
            story_id="AG3-001",
            story_type=StoryType.IMPLEMENTATION,
            mode=StoryMode.EXPLORATION,
            issue_nr=1,
            title="Test story",
            created_at=now,
        )
        data = ctx.model_dump(mode="json")
        restored = StoryContext.model_validate(data)
        assert restored.story_id == ctx.story_id
        assert restored.story_type == ctx.story_type
        assert restored.mode == ctx.mode
        assert restored.issue_nr == ctx.issue_nr

    def test_default_lists_are_independent(self) -> None:
        """Verify mutable default lists are not shared between instances."""
        ctx1 = StoryContext(
            story_id="AG3-001",
            story_type=StoryType.CONCEPT,
            mode=StoryMode.NOT_APPLICABLE,
        )
        ctx2 = StoryContext(
            story_id="AG3-002",
            story_type=StoryType.CONCEPT,
            mode=StoryMode.NOT_APPLICABLE,
        )
        assert ctx1.labels is not ctx2.labels
        assert ctx1.participating_repos is not ctx2.participating_repos


class TestPhaseState:
    """Tests for the PhaseState model."""

    def test_minimal_creation(self) -> None:
        state = PhaseState(
            story_id="AG3-001",
            phase="setup",
            status=PhaseStatus.PENDING,
        )
        assert state.story_id == "AG3-001"
        assert state.phase == "setup"
        assert state.status == PhaseStatus.PENDING
        assert state.paused_reason is None
        assert state.review_round == 0
        assert state.errors == []
        assert state.attempt_id is None

    def test_full_creation(self) -> None:
        state = PhaseState(
            story_id="AG3-001",
            phase="verify",
            status=PhaseStatus.PAUSED,
            paused_reason="Awaiting manual review",
            review_round=2,
            errors=["Test coverage below threshold"],
            attempt_id="attempt-abc123",
        )
        assert state.paused_reason == "Awaiting manual review"
        assert state.review_round == 2
        assert state.errors == ["Test coverage below threshold"]
        assert state.attempt_id == "attempt-abc123"

    def test_mutable_update(self) -> None:
        """PhaseState is mutable -- status changes during execution."""
        state = PhaseState(
            story_id="AG3-001",
            phase="setup",
            status=PhaseStatus.PENDING,
        )
        state.status = PhaseStatus.IN_PROGRESS
        assert state.status == PhaseStatus.IN_PROGRESS

    def test_serialization_roundtrip(self) -> None:
        state = PhaseState(
            story_id="AG3-001",
            phase="verify",
            status=PhaseStatus.FAILED,
            errors=["Build failed"],
            review_round=1,
        )
        data = state.model_dump(mode="json")
        restored = PhaseState.model_validate(data)
        assert restored.story_id == state.story_id
        assert restored.phase == state.phase
        assert restored.status == state.status
        assert restored.errors == state.errors

    def test_default_errors_are_independent(self) -> None:
        s1 = PhaseState(story_id="A", phase="x", status=PhaseStatus.PENDING)
        s2 = PhaseState(story_id="B", phase="y", status=PhaseStatus.PENDING)
        assert s1.errors is not s2.errors


class TestPhaseSnapshot:
    """Tests for the PhaseSnapshot model."""

    def test_creation(self) -> None:
        now = datetime.now(tz=UTC)
        snap = PhaseSnapshot(
            story_id="AG3-001",
            phase="setup",
            status=PhaseStatus.COMPLETED,
            completed_at=now,
            artifacts=["context.json"],
            evidence={"worktree_created": True},
        )
        assert snap.story_id == "AG3-001"
        assert snap.phase == "setup"
        assert snap.status == PhaseStatus.COMPLETED
        assert snap.completed_at == now
        assert snap.artifacts == ["context.json"]
        assert snap.evidence == {"worktree_created": True}

    def test_frozen_model(self) -> None:
        now = datetime.now(tz=UTC)
        snap = PhaseSnapshot(
            story_id="AG3-001",
            phase="setup",
            status=PhaseStatus.COMPLETED,
            completed_at=now,
        )
        with pytest.raises(ValidationError):
            snap.status = PhaseStatus.FAILED  # type: ignore[misc]

    def test_defaults(self) -> None:
        now = datetime.now(tz=UTC)
        snap = PhaseSnapshot(
            story_id="AG3-001",
            phase="setup",
            status=PhaseStatus.COMPLETED,
            completed_at=now,
        )
        assert snap.artifacts == []
        assert snap.evidence == {}

    def test_serialization_roundtrip(self) -> None:
        now = datetime.now(tz=UTC)
        snap = PhaseSnapshot(
            story_id="AG3-001",
            phase="verify",
            status=PhaseStatus.COMPLETED,
            completed_at=now,
            artifacts=["semantic-review.json", "guardrail.json"],
            evidence={"qa_passed": True, "layers_completed": 4},
        )
        data = snap.model_dump(mode="json")
        restored = PhaseSnapshot.model_validate(data)
        assert restored.story_id == snap.story_id
        assert restored.artifacts == snap.artifacts
        assert restored.evidence == snap.evidence
