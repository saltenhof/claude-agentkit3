"""Unit tests for SetupPhaseHandler.

Mocks only the three external system boundaries:
  - run_preflight  (GitHub CLI call)
  - build_story_context  (GitHub CLI call)
  - create_worktree  (git subprocess call)
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from agentkit.exceptions import WorktreeError
from agentkit.pipeline.phases.setup.phase import SetupConfig, SetupPhaseHandler
from agentkit.story.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_preflight_pass() -> object:
    """Return a fake PreflightResult that passes all checks."""

    class _Result:
        passed = True
        checks: list[object] = []

    return _Result()


def _make_preflight_fail(message: str = "issue not open") -> object:
    """Return a fake PreflightResult that fails."""

    class _Check:
        def __init__(self, passed: bool, msg: str) -> None:
            self.passed = passed
            self.message = msg

    class _Result:
        passed = False
        checks = [_Check(False, message)]

    return _Result()


def _make_story_context(
    story_id: str = "AG3-001",
    story_type: StoryType = StoryType.IMPLEMENTATION,
    project_root: Path | None = None,
) -> StoryContext:
    """Build a minimal StoryContext for testing."""
    if story_type == StoryType.IMPLEMENTATION:
        mode = StoryMode.EXPLORATION
    else:
        mode = StoryMode.NOT_APPLICABLE
    return StoryContext(
        story_id=story_id,
        story_type=story_type,
        mode=mode,
        issue_nr=1,
        title="Test Story",
        project_root=project_root,
    )


def _make_phase_state(story_id: str = "AG3-001") -> PhaseState:
    return PhaseState(
        story_id=story_id,
        phase="setup",
        status=PhaseStatus.IN_PROGRESS,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSetupPhaseHandlerWorktree:
    """Tests for worktree creation in SetupPhaseHandler.on_enter."""

    def test_create_worktree_called_for_implementation(
        self, tmp_path: Path
    ) -> None:
        """on_enter creates a worktree for an implementation story."""
        cfg = SetupConfig(
            owner="owner",
            repo="repo",
            issue_nr=1,
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=True,
        )
        handler = SetupPhaseHandler(cfg)
        ctx = _make_story_context(project_root=tmp_path)
        state = _make_phase_state()
        enriched = _make_story_context(project_root=tmp_path)

        with (
            patch(
                "agentkit.pipeline.phases.setup.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.create_worktree"
            ) as mock_create,
        ):
            result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["branch"] == "story/AG3-001"

    def test_create_worktree_not_called_for_concept(
        self, tmp_path: Path
    ) -> None:
        """on_enter does not create a worktree for a concept story."""
        cfg = SetupConfig(
            owner="owner",
            repo="repo",
            issue_nr=2,
            project_root=tmp_path,
            story_id="AG3-002",
            create_worktree=True,
        )
        handler = SetupPhaseHandler(cfg)
        ctx = _make_story_context(
            story_id="AG3-002",
            story_type=StoryType.CONCEPT,
            project_root=tmp_path,
        )
        state = _make_phase_state(story_id="AG3-002")
        enriched = _make_story_context(
            story_id="AG3-002",
            story_type=StoryType.CONCEPT,
            project_root=tmp_path,
        )

        with (
            patch(
                "agentkit.pipeline.phases.setup.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.create_worktree"
            ) as mock_create,
        ):
            result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED
        mock_create.assert_not_called()

    def test_create_worktree_failure_returns_failed(
        self, tmp_path: Path
    ) -> None:
        """on_enter returns FAILED when create_worktree raises WorktreeError."""
        cfg = SetupConfig(
            owner="owner",
            repo="repo",
            issue_nr=3,
            project_root=tmp_path,
            story_id="AG3-003",
            create_worktree=True,
        )
        handler = SetupPhaseHandler(cfg)
        ctx = _make_story_context(story_id="AG3-003", project_root=tmp_path)
        state = _make_phase_state(story_id="AG3-003")
        enriched = _make_story_context(story_id="AG3-003", project_root=tmp_path)

        with (
            patch(
                "agentkit.pipeline.phases.setup.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.create_worktree",
                side_effect=WorktreeError(
                    "Worktree path already exists: /some/path"
                ),
            ),
        ):
            result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.FAILED
        assert len(result.errors) == 1
        assert "Worktree path already exists" in result.errors[0]

    def test_worktree_created_but_persist_fails_cleans_up(
        self, tmp_path: Path
    ) -> None:
        """on_enter removes the worktree and returns FAILED when the second
        save_story_context call (which persists the worktree path) raises."""
        cfg = SetupConfig(
            owner="owner",
            repo="repo",
            issue_nr=5,
            project_root=tmp_path,
            story_id="AG3-005",
            create_worktree=True,
        )
        handler = SetupPhaseHandler(cfg)
        ctx = _make_story_context(story_id="AG3-005", project_root=tmp_path)
        state = _make_phase_state(story_id="AG3-005")
        enriched = _make_story_context(story_id="AG3-005", project_root=tmp_path)

        with (
            patch(
                "agentkit.pipeline.phases.setup.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.create_worktree",
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.save_story_context",
                # First call (initial save) succeeds; second call (with worktree
                # path) raises to simulate a disk-full or permission error.
                side_effect=[None, OSError("disk full")],
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.remove_worktree",
            ) as mock_remove,
        ):
            result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.FAILED
        assert "disk full" in result.errors[0]
        # Cleanup must have been attempted to avoid a leaked worktree.
        mock_remove.assert_called_once()

    def test_preflight_failure_returns_failed(self, tmp_path: Path) -> None:
        """on_enter returns FAILED immediately when preflight fails."""
        cfg = SetupConfig(
            owner="owner",
            repo="repo",
            issue_nr=4,
            project_root=tmp_path,
            story_id="AG3-004",
        )
        handler = SetupPhaseHandler(cfg)
        ctx = _make_story_context(story_id="AG3-004", project_root=tmp_path)
        state = _make_phase_state(story_id="AG3-004")

        with (
            patch(
                "agentkit.pipeline.phases.setup.phase.run_preflight",
                return_value=_make_preflight_fail("issue is closed"),
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.build_story_context"
            ) as mock_build,
            patch(
                "agentkit.pipeline.phases.setup.phase.create_worktree"
            ) as mock_create,
        ):
            result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.FAILED
        assert "issue is closed" in result.errors[0]
        mock_build.assert_not_called()
        mock_create.assert_not_called()
