"""Integration tests for the ClosurePhaseHandler against live GitHub.

Testbed: saltenhof/agentkit3-testbed

These tests exercise the ClosurePhaseHandler in isolation with real
GitHub operations. They are NOT full pipeline E2E tests -- prior-phase
snapshots are created directly via ``save_phase_snapshot()``, not by
running the actual pipeline. This is acceptable for handler-level
integration testing but does not prove the full production path.

For real E2E pipeline tests, see ``tests/e2e/smoke/test_real_pipeline.py``.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.installer import InstallConfig, install_agentkit
from agentkit.installer.paths import story_dir
from agentkit.integrations.github.issues import (
    create_issue,
    get_issue,
    reopen_issue,
)
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline.phases.closure.phase import (
    ClosureConfig,
    ClosurePhaseHandler,
)
from agentkit.pipeline.phases.setup.phase import SetupConfig, SetupPhaseHandler
from agentkit.pipeline.state import save_phase_snapshot
from agentkit.state_backend import save_flow_execution
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

OWNER = "saltenhof"
REPO = "agentkit3-testbed"


def _save_snapshot(
    s_dir: Path,
    phase: str,
    story_id: str = "E2E-CLOSURE",
) -> None:
    """Persist a completed phase snapshot to disk."""
    snapshot = PhaseSnapshot(
        story_id=story_id,
        phase=phase,
        status=PhaseStatus.COMPLETED,
        completed_at=datetime.now(tz=UTC),
        artifacts=[],
        evidence={},
    )
    save_phase_snapshot(s_dir, snapshot)


def _save_flow(
    s_dir: Path,
    *,
    project_key: str,
    story_id: str,
) -> None:
    save_flow_execution(
        s_dir,
        FlowExecution(
            project_key=project_key,
            story_id=story_id,
            run_id=f"run-{story_id.lower()}",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="COMPLETED",
            started_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        ),
    )


@pytest.mark.integration
@pytest.mark.requires_gh
class TestClosurePhaseE2E:
    """Integration tests for the closure phase handler against real GitHub.

    These test the ClosurePhaseHandler's logic with real GitHub I/O,
    but prior-phase state is constructed directly -- not produced by
    running prior pipeline phases. This makes them handler-level
    integration tests, not full pipeline E2E tests.
    """

    def test_closure_closes_real_issue(self, tmp_path: Path) -> None:
        """Closure phase closes a real GitHub issue."""
        # 1. Create a fresh issue in the testbed
        issue = create_issue(
            OWNER,
            REPO,
            title="[E2E] Closure test issue",
            body="Automated test -- will be closed and reopened.",
        )
        issue_nr = issue.number

        try:
            # 2. Create snapshots for all prior phases (bugfix profile)
            s_dir = tmp_path / "stories" / "E2E-CLOSURE"
            s_dir.mkdir(parents=True)
            for phase in ("setup", "implementation", "verify"):
                _save_snapshot(s_dir, phase)
            _save_flow(
                s_dir,
                project_key="e2e-closure-test",
                story_id="E2E-CLOSURE",
            )

            # 3. Run closure handler
            config = ClosureConfig(
                owner=OWNER,
                repo=REPO,
                issue_nr=issue_nr,
                close_issue=True,
                story_dir=s_dir,
            )
            handler = ClosurePhaseHandler(config)
            ctx = StoryContext(
                project_key="e2e-closure-test",
                story_id="E2E-CLOSURE",
                story_type=StoryType.BUGFIX,
                execution_route=StoryMode.EXECUTION,
            )
            state = PhaseState(
                story_id="E2E-CLOSURE",
                phase="closure",
                status=PhaseStatus.IN_PROGRESS,
            )

            result = handler.on_enter(ctx, state)

            # 4. Verify COMPLETED and issue is CLOSED
            assert result.status == PhaseStatus.COMPLETED
            closed_issue = get_issue(OWNER, REPO, issue_nr)
            assert closed_issue.state == "CLOSED"

            # Verify closure.json exists
            assert (s_dir / "closure.json").exists()

        finally:
            # 5. Cleanup: reopen the issue
            with contextlib.suppress(Exception):
                reopen_issue(OWNER, REPO, issue_nr)

    def test_full_pipeline_setup_to_closure(self, tmp_path: Path) -> None:
        """Complete pipeline: install -> setup -> NoOp middle -> closure.

        This is the central E2E test: setup to closure with real GitHub.
        """
        # 1. Install AgentKit
        install_agentkit(
            InstallConfig(
                project_key="e2e-closure-test",
                project_name="e2e-closure-test",
                project_root=tmp_path,
            )
        )

        # 2. Create a fresh issue
        issue = create_issue(
            OWNER,
            REPO,
            title="[E2E] Full pipeline closure test",
            body="Automated test -- setup to closure.",
        )
        issue_nr = issue.number

        try:
            # 3. Setup phase with real issue
            setup_config = SetupConfig(
                owner=OWNER,
                repo=REPO,
                issue_nr=issue_nr,
                project_root=tmp_path,
                story_id="E2E-FULL",
                create_worktree=False,
            )
            setup_handler = SetupPhaseHandler(setup_config)

            ctx = StoryContext(
                project_key="e2e-closure-test",
                story_id="E2E-FULL",
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
            )
            state = PhaseState(
                story_id="E2E-FULL",
                phase="setup",
                status=PhaseStatus.IN_PROGRESS,
            )

            setup_result = setup_handler.on_enter(ctx, state)
            assert setup_result.status == PhaseStatus.COMPLETED

            # 4. NoOp snapshots for exploration, implementation, verify
            s_dir = story_dir(tmp_path, "E2E-FULL")
            for phase in ("exploration", "implementation", "verify"):
                _save_snapshot(s_dir, phase, story_id="E2E-FULL")

            # Also save setup snapshot (setup handler produces context,
            # but the engine would normally save the snapshot)
            _save_snapshot(s_dir, "setup", story_id="E2E-FULL")
            _save_flow(
                s_dir,
                project_key="e2e-closure-test",
                story_id="E2E-FULL",
            )

            # 5. Closure with close_issue=True
            closure_config = ClosureConfig(
                owner=OWNER,
                repo=REPO,
                issue_nr=issue_nr,
                close_issue=True,
                story_dir=s_dir,
            )
            closure_handler = ClosurePhaseHandler(closure_config)

            closure_ctx = StoryContext(
                project_key="e2e-closure-test",
                story_id="E2E-FULL",
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
            )
            closure_state = PhaseState(
                story_id="E2E-FULL",
                phase="closure",
                status=PhaseStatus.IN_PROGRESS,
            )

            closure_result = closure_handler.on_enter(
                closure_ctx,
                closure_state,
            )

            # 6. Verify
            assert closure_result.status == PhaseStatus.COMPLETED
            assert (s_dir / "closure.json").exists()

            closed_issue = get_issue(OWNER, REPO, issue_nr)
            assert closed_issue.state == "CLOSED"

        finally:
            # 7. Cleanup: reopen the issue
            with contextlib.suppress(Exception):
                reopen_issue(OWNER, REPO, issue_nr)
