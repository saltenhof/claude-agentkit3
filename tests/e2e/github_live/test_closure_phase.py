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
import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.e2e._helpers import seed_approved_story

from agentkit.backend.bootstrap.composition_root import (
    build_closure_phase_handler,
    build_setup_phase_handler,
)
from agentkit.backend.closure.phase import ClosureConfig
from agentkit.backend.governance.setup_preflight_gate.phase import SetupConfig
from agentkit.backend.installer import InstallConfig, install_agentkit
from agentkit.backend.installer.paths import qa_story_dir, story_dir
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.pipeline_engine.phase_executor import (
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
)
from agentkit.backend.state_backend.store import (
    append_execution_event,
    save_flow_execution,
    save_phase_snapshot,
    save_story_context,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import StoryStatus, WireStoryType
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType
from agentkit.integration_clients.github.issues import (
    create_issue,
    get_issue,
    reopen_issue,
)

if TYPE_CHECKING:
    from pathlib import Path

OWNER = "saltenhof"
REPO = "agentkit3-testbed"


def _save_snapshot(
    s_dir: Path,
    phase: str,
    story_id: str = "E2E-7001",
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


def _append_agent_start(
    s_dir: Path,
    *,
    project_key: str,
    story_id: str,
) -> None:
    append_execution_event(
        s_dir,
        ExecutionEventRecord(
            project_key=project_key,
            story_id=story_id,
            run_id=f"run-{story_id.lower()}",
            event_id=f"evt-agent-start-{story_id.lower()}",
            event_type=EventType.AGENT_START.value,
            occurred_at=datetime(2026, 1, 1, 9, 45, 0, tzinfo=UTC),
            source_component="telemetry-test",
            severity="info",
            payload={"agent_type": "pipeline_engine"},
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
            # 2. Create snapshots for all prior phases (bugfix profile:
            #    setup -> implementation -> closure; verify is an internal
            #    Implementation subflow, not a top-level phase, FK-27).
            s_dir = tmp_path / "stories" / "E2E-7001"
            s_dir.mkdir(parents=True)
            for phase in ("setup", "implementation"):
                _save_snapshot(s_dir, phase)
            _save_flow(
                s_dir,
                project_key="e2e-closure-test",
                story_id="E2E-7001",
            )
            _append_agent_start(
                s_dir,
                project_key="e2e-closure-test",
                story_id="E2E-7001",
            )

            # Seed an IN_PROGRESS Story so closure's complete_story
            # (In Progress -> Done) succeeds. Closure runs standalone here,
            # so Setup's begin_progress never executed -- the story must
            # already be In Progress (real StoryService persistence, no mock).
            # CONCEPT shares the bugfix phase profile (setup -> implementation
            # -> closure) but skips the merge block (uses_merge=False, FK-29
            # §29.1.1), so closure here closes the issue + runs finalization
            # without needing a live merge/Sonar environment.
            seed_approved_story(
                project_key="e2e-closure-test",
                story_display_id="E2E-7001",
                story_number=1,
                story_type=WireStoryType.CONCEPT,
                title="E2E closure: closes real issue",
                status=StoryStatus.IN_PROGRESS,
            )

            # 3. Run closure handler (wired via the composition root). The
            # comp-root fail-closes (FIX-2) on a missing story context, so persist
            # a context carrying ``project_root`` before wiring the handler.
            ctx = StoryContext(
                project_key="e2e-closure-test",
                story_id="E2E-7001",
                story_type=StoryType.CONCEPT,
                execution_route=None,  # CONCEPT allows only execution_route=None
                project_root=tmp_path,
            )
            save_story_context(s_dir, ctx)
            config = ClosureConfig(
                owner=OWNER,
                repo=REPO,
                issue_nr=issue_nr,
                close_issue=True,
                story_dir=s_dir,
            )
            handler = build_closure_phase_handler(
                config, store_dir=s_dir, project_key="e2e-closure-test"
            )
            state = PhaseState(
                story_id="E2E-7001",
                phase="closure",
                status=PhaseStatus.IN_PROGRESS,
            )

            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

            # 4. Verify COMPLETED and issue is CLOSED
            assert result.status == PhaseStatus.COMPLETED
            closed_issue = get_issue(OWNER, REPO, issue_nr)
            assert closed_issue.state == "CLOSED"

            # Verify closure.json exists
            assert (qa_story_dir(tmp_path, "E2E-7001") / "closure.json").exists()

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
                github_owner="acme",  # AG3-039 R6: CP 7 coordinates are MANDATORY
                github_repo="demo",
                sonarqube_available=False,  # AG3-052: conscious opt-out, no live Sonar
                ci_available=False,  # AG3-056: conscious opt-out, no live Jenkins
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
                story_id="E2E-7002",
                create_worktree=False,
            )
            # AG3-034 Finding B: Preflight Check 7 reads the real repo; init one.
            subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
            subprocess.run(
                ["git", "-C", str(tmp_path), "config", "user.email", "t@e.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True
            )
            setup_handler = build_setup_phase_handler(setup_config)

            # Seed the APPROVED Story the Setup preflight gate requires.
            # Setup transitions Approved -> In Progress, closure In Progress
            # -> Done (real StoryService persistence, no mock).
            # CONCEPT skips the merge block (uses_merge=False, FK-29 §29.1.1):
            # closure closes the issue + runs finalization without a live
            # merge/Sonar environment. (The setup phase still runs for real.)
            seed_approved_story(
                project_key="e2e-closure-test",
                story_display_id="E2E-7002",
                story_number=2,
                story_type=WireStoryType.CONCEPT,
                title="E2E full pipeline: setup to closure",
            )

            ctx = StoryContext(
                project_key="e2e-closure-test",
                story_id="E2E-7002",
                story_type=StoryType.CONCEPT,
                execution_route=None,  # CONCEPT allows only execution_route=None
            )
            state = PhaseState(
                story_id="E2E-7002",
                phase="setup",
                status=PhaseStatus.IN_PROGRESS,
            )

            setup_result = setup_handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))
            assert setup_result.status == PhaseStatus.COMPLETED

            # 4. NoOp snapshots for the implementation profile's prior phases
            #    (setup, exploration, implementation). verify is an internal
            #    Implementation subflow, not a top-level phase (FK-27).
            s_dir = story_dir(tmp_path, "E2E-7002")
            for phase in ("exploration", "implementation"):
                _save_snapshot(s_dir, phase, story_id="E2E-7002")

            # Also save setup snapshot (setup handler produces context,
            # but the engine would normally save the snapshot)
            _save_snapshot(s_dir, "setup", story_id="E2E-7002")
            _save_flow(
                s_dir,
                project_key="e2e-closure-test",
                story_id="E2E-7002",
            )
            _append_agent_start(
                s_dir,
                project_key="e2e-closure-test",
                story_id="E2E-7002",
            )

            # 5. Closure with close_issue=True
            closure_config = ClosureConfig(
                owner=OWNER,
                repo=REPO,
                issue_nr=issue_nr,
                close_issue=True,
                story_dir=s_dir,
            )
            closure_handler = build_closure_phase_handler(
                closure_config, store_dir=s_dir, project_key="e2e-closure-test"
            )

            closure_ctx = StoryContext(
                project_key="e2e-closure-test",
                story_id="E2E-7002",
                story_type=StoryType.CONCEPT,
                execution_route=None,  # CONCEPT allows only execution_route=None
            )
            closure_state = PhaseState(
                story_id="E2E-7002",
                phase="closure",
                status=PhaseStatus.IN_PROGRESS,
            )

            closure_result = closure_handler.on_enter(
                closure_ctx,
                PhaseEnvelopeStore.make_fresh_envelope(closure_state),
            )

            # 6. Verify
            assert closure_result.status == PhaseStatus.COMPLETED
            assert (qa_story_dir(tmp_path, "E2E-7002") / "closure.json").exists()

            closed_issue = get_issue(OWNER, REPO, issue_nr)
            assert closed_issue.state == "CLOSED"

        finally:
            # 7. Cleanup: reopen the issue
            with contextlib.suppress(Exception):
                reopen_issue(OWNER, REPO, issue_nr)
