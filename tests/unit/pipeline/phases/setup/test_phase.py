"""Unit tests for SetupPhaseHandler.

Mocks only the three external system boundaries:
  - run_preflight  (StoryService-based, mocked)
  - build_story_context  (GitHub CLI call)
  - create_worktree  (git subprocess call)
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from agentkit.config.models import ProjectConfig, RepositoryConfig
from agentkit.exceptions import WorktreeError
from agentkit.pipeline.phases.setup.phase import SetupConfig, SetupPhaseHandler
from agentkit.pipeline.phases.setup.worktree import WorktreeResult
from agentkit.story_context_manager.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

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
    project_key: str = "test-project",
) -> StoryContext:
    """Build a minimal StoryContext for testing."""
    mode = StoryMode.EXPLORATION if story_type == StoryType.IMPLEMENTATION else StoryMode.NOT_APPLICABLE
    return StoryContext(
        project_key=project_key,
        story_id=story_id,
        story_type=story_type,
        execution_route=mode,
        issue_nr=1,
        title="Test Story",
        project_root=project_root,
        participating_repos=["repo"],
    )


def _make_phase_state(story_id: str = "AG3-001") -> PhaseState:
    return PhaseState(
        story_id=story_id,
        phase="setup",
        status=PhaseStatus.IN_PROGRESS,
    )


def _make_project_config(repo_path: Path) -> ProjectConfig:
    return ProjectConfig(
        project_key="test-project",
        project_name="Test Project",
        repositories=[RepositoryConfig(name="repo", path=repo_path)],
    )


def _make_worktree_result(tmp_path: Path, story_id: str = "AG3-001") -> WorktreeResult:
    return WorktreeResult(
        success=True,
        worktree_path=tmp_path / "worktrees" / story_id,
        repo_name="repo",
        branch=f"story/{story_id}",
    )


# ---------------------------------------------------------------------------
# Helpers (continued)
# ---------------------------------------------------------------------------


class _NoOpStoryService:
    """Minimal no-op stub for SetupPhaseHandler tests that don't test begin_progress."""

    def begin_progress(self, story_id: str, *, correlation_id: str = "") -> object:
        return object()


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
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
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
                "agentkit.pipeline.phases.setup.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.setup_worktrees",
                return_value=[_make_worktree_result(tmp_path)],
            ) as mock_setup,
        ):
            result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED
        mock_setup.assert_called_once()
        assert mock_setup.call_args.args[0] == "AG3-001"
        assert result.updated_context is not None
        assert result.updated_context.worktree_map == {
            "repo": tmp_path / "worktrees" / "AG3-001",
        }

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
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
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
                "agentkit.pipeline.phases.setup.phase.setup_worktrees"
            ) as mock_setup,
        ):
            result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED
        mock_setup.assert_not_called()

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
                "agentkit.pipeline.phases.setup.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.setup_worktrees",
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
                "agentkit.pipeline.phases.setup.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.setup_worktrees",
                return_value=[_make_worktree_result(tmp_path, "AG3-005")],
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
                "agentkit.pipeline.phases.setup.phase.setup_worktrees"
            ) as mock_setup,
        ):
            result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.FAILED
        assert "issue is closed" in result.errors[0]
        mock_build.assert_not_called()
        mock_setup.assert_not_called()


class TestSetupPhaseBeginProgress:
    """Tests for begin_progress call on successful setup."""

    def test_begin_progress_called_on_success(self, tmp_path: Path) -> None:
        """begin_progress is called when story_service is provided and setup succeeds."""
        calls: list[str] = []

        class _StubService:
            def begin_progress(self, story_id: str, *, correlation_id: str = "") -> object:
                calls.append(story_id)
                return object()

        svc = _StubService()
        cfg = SetupConfig(
            owner="owner",
            repo="repo",
            issue_nr=1,
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=False,
            story_service=svc,  # type: ignore[arg-type]
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
        ):
            result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED
        assert calls == ["AG3-001"]

    def test_begin_progress_called_via_default_service_when_none(
        self, tmp_path: Path
    ) -> None:
        """When story_service is None, a default StoryService is constructed and used.

        Befund 9: story_service=None must NOT silently skip begin_progress.
        A default StoryService is constructed so begin_progress is always called.
        """
        calls: list[str] = []

        class _TrackingService:
            def begin_progress(self, story_id: str, *, correlation_id: str = "") -> object:
                calls.append(story_id)
                return object()

        cfg = SetupConfig(
            owner="owner",
            repo="repo",
            issue_nr=1,
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=False,
            story_service=None,
        )
        handler = SetupPhaseHandler(cfg)
        ctx = _make_story_context(project_root=tmp_path)
        state = _make_phase_state()
        enriched = _make_story_context(project_root=tmp_path)

        tracking_svc = _TrackingService()
        with (
            patch(
                "agentkit.pipeline.phases.setup.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.pipeline.phases.setup.phase.build_story_context",
                return_value=enriched,
            ),
            # Patch StoryService at its source so the default construction
            # inside on_enter returns our tracking service (Befund 9).
            patch(
                "agentkit.story_context_manager.service.StoryService",
                return_value=tracking_svc,
            ),
        ):
            result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.COMPLETED
        # begin_progress must be called even when story_service=None (Befund 9)
        assert calls == ["AG3-001"]

    def test_begin_progress_failure_returns_failed(self, tmp_path: Path) -> None:
        """on_enter returns FAILED when begin_progress raises."""

        class _FailingService:
            def begin_progress(self, story_id: str, *, correlation_id: str = "") -> object:
                raise RuntimeError("transition error: not Approved")

        cfg = SetupConfig(
            owner="owner",
            repo="repo",
            issue_nr=1,
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=False,
            story_service=_FailingService(),  # type: ignore[arg-type]
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
        ):
            result = handler.on_enter(ctx, state)

        assert result.status == PhaseStatus.FAILED
        assert "begin_progress failed" in result.errors[0]
        assert "transition error" in result.errors[0]
