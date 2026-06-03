"""Unit tests for SetupPhaseHandler.

Mocks only the three external system boundaries:
  - run_preflight  (StoryService-based, mocked)
  - build_story_context  (GitHub CLI call)
  - create_worktree  (git subprocess call)

AG3-031 Pass-4 Fix E9: save_story_context is no longer a module-level name.
Tests use a _RecordingContextRepo test-double for the persist-failure path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from agentkit.config.models import (
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)
from agentkit.exceptions import WorktreeError
from agentkit.governance.setup_preflight_gate.phase import SetupConfig, SetupPhaseHandler
from agentkit.governance.setup_preflight_gate.worktree import WorktreeResult
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.story_context_manager.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Recording test-double for SetupContextRepository (Fix E9)
# ---------------------------------------------------------------------------


class _RecordingContextRepo:
    """Recording test-double for SetupContextRepository.

    Configurable: ``_raises_on_call`` controls whether ``save`` raises an
    exception on the N-th call.
    """

    def __init__(self, raises_on_call: int | None = None, exc: Exception | None = None) -> None:
        self.calls: list[tuple[object, object]] = []
        self._raises_on_call = raises_on_call
        self._exc = exc or OSError("disk full")

    def save(self, story_dir: Path, ctx: StoryContext) -> None:
        call_no = len(self.calls) + 1
        self.calls.append((story_dir, ctx))
        if self._raises_on_call is not None and call_no == self._raises_on_call:
            raise self._exc


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
    mode: StoryMode | None = (
        StoryMode.EXPLORATION
        if story_type == StoryType.IMPLEMENTATION
        else None
    )
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
        # AG3-052 E6: code-producing default story_types => declare sonarqube.
        pipeline=PipelineConfig(
            sonarqube=SonarQubeConfig(available=False, enabled=False)
        ),
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
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())  # type: ignore[arg-type]
        ctx = _make_story_context(project_root=tmp_path)
        state = _make_phase_state()
        enriched = _make_story_context(project_root=tmp_path)

        with (
            patch(
                "agentkit.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.setup_worktrees",
                return_value=[_make_worktree_result(tmp_path)],
            ) as mock_setup,
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

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
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())  # type: ignore[arg-type]
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
                "agentkit.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.setup_worktrees"
            ) as mock_setup,
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

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
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())  # type: ignore[arg-type]
        ctx = _make_story_context(story_id="AG3-003", project_root=tmp_path)
        state = _make_phase_state(story_id="AG3-003")
        enriched = _make_story_context(story_id="AG3-003", project_root=tmp_path)

        with (
            patch(
                "agentkit.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.setup_worktrees",
                side_effect=WorktreeError(
                    "Worktree path already exists: /some/path"
                ),
            ),
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status == PhaseStatus.FAILED
        assert len(result.errors) == 1
        assert "Worktree path already exists" in result.errors[0]

    def test_worktree_created_but_persist_fails_cleans_up(
        self, tmp_path: Path
    ) -> None:
        """on_enter removes the worktree and returns FAILED when the second
        context_repo.save call (which persists the worktree path) raises.

        AG3-031 Pass-4 Fix E9: uses _RecordingContextRepo test-double instead
        of patching the now-removed module-level save_story_context name.
        """
        # Second call (with worktree path) raises to simulate disk-full.
        ctx_repo = _RecordingContextRepo(raises_on_call=2, exc=OSError("disk full"))

        cfg = SetupConfig(
            owner="owner",
            repo="repo",
            issue_nr=5,
            project_root=tmp_path,
            story_id="AG3-005",
            create_worktree=True,
        )
        handler = SetupPhaseHandler(cfg, context_repository=ctx_repo)  # type: ignore[arg-type]
        ctx = _make_story_context(story_id="AG3-005", project_root=tmp_path)
        state = _make_phase_state(story_id="AG3-005")
        enriched = _make_story_context(story_id="AG3-005", project_root=tmp_path)

        with (
            patch(
                "agentkit.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.setup_worktrees",
                return_value=[_make_worktree_result(tmp_path, "AG3-005")],
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.remove_worktree",
            ) as mock_remove,
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

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
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())
        ctx = _make_story_context(story_id="AG3-004", project_root=tmp_path)
        state = _make_phase_state(story_id="AG3-004")

        with (
            patch(
                "agentkit.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_fail("issue is closed"),
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.build_story_context"
            ) as mock_build,
            patch(
                "agentkit.governance.setup_preflight_gate.phase.setup_worktrees"
            ) as mock_setup,
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

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
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())
        ctx = _make_story_context(project_root=tmp_path)
        state = _make_phase_state()
        enriched = _make_story_context(project_root=tmp_path)

        with (
            patch(
                "agentkit.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

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
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())
        ctx = _make_story_context(project_root=tmp_path)
        state = _make_phase_state()
        enriched = _make_story_context(project_root=tmp_path)

        tracking_svc = _TrackingService()
        with (
            patch(
                "agentkit.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            # Patch StoryService at its source so the default construction
            # inside on_enter returns our tracking service (Befund 9).
            patch(
                "agentkit.story_context_manager.service.StoryService",
                return_value=tracking_svc,
            ),
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

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
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())
        ctx = _make_story_context(project_root=tmp_path)
        state = _make_phase_state()
        enriched = _make_story_context(project_root=tmp_path)

        with (
            patch(
                "agentkit.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status == PhaseStatus.FAILED
        assert "begin_progress failed" in result.errors[0]
        assert "transition error" in result.errors[0]
