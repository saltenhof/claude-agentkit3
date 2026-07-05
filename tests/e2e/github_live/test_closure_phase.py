"""Integration tests for the ClosurePhaseHandler (setup -> closure).

Testbed: saltenhof/agentkit3-testbed

These tests exercise the ClosurePhaseHandler in isolation with the real
state-backend. They are NOT full pipeline E2E tests -- prior-phase
snapshots are created directly via ``save_phase_snapshot()``, not by
running the actual pipeline. This is acceptable for handler-level
integration testing but does not prove the full production path.

AG3-120: AK3 owns the user story via ``story_id``; GitHub is only the code
backend (FK-12 §12.1.1, FK-91 §91.2 rule 9). Closure closes the story via the
AK3 Story-Service (In Progress -> Done), NOT by closing a GitHub issue. The
former ``test_closure_closes_real_issue`` test was removed with that coupling.

For real E2E pipeline tests, see ``tests/e2e/smoke/test_real_pipeline.py``.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.e2e._helpers import seed_active_run_ownership, seed_approved_story
from tests.phase_state_factory import make_phase_state

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
    PhaseStatus,
)
from agentkit.backend.state_backend.store import (
    append_execution_event,
    save_flow_execution,
    save_phase_snapshot,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import WireStoryType
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType

if TYPE_CHECKING:
    from pathlib import Path


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
    run_id: str,
) -> None:
    save_flow_execution(
        s_dir,
        FlowExecution(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
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
    run_id: str,
) -> None:
    append_execution_event(
        s_dir,
        ExecutionEventRecord(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            event_id=f"evt-agent-start-{story_id.lower()}",
            event_type=EventType.AGENT_START.value,
            occurred_at=datetime(2026, 1, 1, 9, 45, 0, tzinfo=UTC),
            source_component="telemetry-test",
            severity="info",
            payload={"agent_type": "pipeline_engine"},
        ),
    )


@pytest.mark.integration
class TestClosurePhaseE2E:
    """Integration tests for the closure phase handler against the real backend.

    These test the ClosurePhaseHandler's logic with the real state-backend,
    but prior-phase state is constructed directly -- not produced by running
    prior pipeline phases. This makes them handler-level integration tests, not
    full pipeline E2E tests. AG3-120: closure no longer touches GitHub; the
    story is closed via the AK3 Story-Service (In Progress -> Done).
    """

    def test_full_pipeline_setup_to_closure(self, tmp_path: Path) -> None:
        """Complete pipeline: install -> setup -> NoOp middle -> closure.

        This is the central E2E test: setup to closure via the AK3 Story-Service,
        with NO GitHub-issue coupling (AG3-120).
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

        # 2. Setup phase. AK3 owns the story via story_id (no GitHub issue input).
        setup_config = SetupConfig(
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
        # closure runs finalization without a live merge/Sonar environment.
        seed_approved_story(
            project_key="e2e-closure-test",
            story_display_id="E2E-7002",
            story_number=2,
            story_type=WireStoryType.CONCEPT,
            title="E2E full pipeline: setup to closure",
        )

        # AG3-144 (Codex round-3): seed the active ownership record a real
        # control-plane setup start would mint BEFORE running setup -- setup's
        # ARE-bundle-load write is now fenced too (7b68f2fc), and this handler
        # is driven directly (no control-plane), so the lease must already be
        # active when ``setup_handler.on_enter`` runs. ``run_id`` is pinned to
        # ONE value shared by the ``PhaseState`` below, the flow execution
        # seeded after setup, and the AGENT_START event -- matching the real
        # invariant that setup start, the phase envelope, and the flow
        # execution all share ONE run id (AG3-142). ``PhaseState.run_id`` is
        # pydantic-validated as a UUID string, so this must be UUID-shaped
        # (unlike ``FlowExecution.run_id`` / ``RunOwnershipRecord.run_id``,
        # which are plain strings).
        run_id = "11111111-1111-4111-8111-e2e070020000"
        seed_active_run_ownership(
            project_key="e2e-closure-test",
            story_id="E2E-7002",
            run_id=run_id,
        )

        ctx = StoryContext(
            project_key="e2e-closure-test",
            story_id="E2E-7002",
            story_type=StoryType.CONCEPT,
            execution_route=None,  # CONCEPT allows only execution_route=None
        )
        state = make_phase_state(
            story_id="E2E-7002",
            phase="setup",
            status=PhaseStatus.IN_PROGRESS,
            story_type=StoryType.CONCEPT,
            run_id=run_id,
        )

        setup_result = setup_handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))
        assert setup_result.status == PhaseStatus.COMPLETED

        # 3. NoOp snapshots for the implementation profile's prior phases
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
            run_id=run_id,
        )
        _append_agent_start(
            s_dir,
            project_key="e2e-closure-test",
            story_id="E2E-7002",
            run_id=run_id,
        )

        # 4. Closure: closes the story via the AK3 Story-Service (no GitHub).
        closure_config = ClosureConfig(story_dir=s_dir)
        closure_handler = build_closure_phase_handler(
            closure_config, store_dir=s_dir, project_key="e2e-closure-test"
        )

        closure_ctx = StoryContext(
            project_key="e2e-closure-test",
            story_id="E2E-7002",
            story_type=StoryType.CONCEPT,
            execution_route=None,  # CONCEPT allows only execution_route=None
        )
        closure_state = make_phase_state(
            story_id="E2E-7002",
            phase="closure",
            status=PhaseStatus.IN_PROGRESS,
            story_type=StoryType.CONCEPT,
        )

        closure_result = closure_handler.on_enter(
            closure_ctx,
            PhaseEnvelopeStore.make_fresh_envelope(closure_state),
        )

        # 5. Verify the story was closed and the closure report was written.
        assert closure_result.status == PhaseStatus.COMPLETED
        assert (qa_story_dir(tmp_path, "E2E-7002") / "closure.json").exists()
