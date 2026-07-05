"""E2E tests for the setup phase against the real state-backend.

AG3-120: AK3 owns the user story via ``story_id``; GitHub is only the code
backend (FK-12 §12.1.1, FK-91 §91.2 rule 9). Setup builds the StoryContext
from the authoritative AK3 Story-Service record, NOT from a GitHub issue.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from tests.e2e._helpers import seed_active_run_ownership, seed_approved_story
from tests.phase_state_factory import make_phase_state

from agentkit.backend.bootstrap.composition_root import build_setup_phase_handler
from agentkit.backend.governance.setup_preflight_gate.phase import SetupConfig
from agentkit.backend.installer import InstallConfig, install_agentkit
from agentkit.backend.installer.paths import story_dir
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.pipeline_engine.phase_executor import (
    PhaseStatus,
)
from agentkit.backend.state_backend.store import read_story_context_record
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import WireStoryType
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


def _init_repo(root: Path) -> None:
    """Init a real git repo (Preflight Check 7 reads it, AG3-034 Finding B)."""
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "t@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)


@pytest.mark.e2e
class TestSetupPhaseE2E:
    """End-to-end tests for the setup phase against the real backend."""

    def test_setup_builds_context_from_story_service(self, tmp_path: Path) -> None:
        """Setup builds the StoryContext from the AK3 Story-Service record.

        No GitHub issue is read (AG3-120): the context is sourced from the
        seeded, authoritative Story-Service record alone.
        """
        # 1. Install AgentKit
        install_agentkit(
            InstallConfig(
                project_key="test",
                project_name="test",
                project_root=tmp_path,
                github_owner="acme",  # AG3-039 R6: CP 7 coordinates are MANDATORY
                github_repo="demo",
                sonarqube_available=False,  # AG3-052: conscious opt-out, no live Sonar
                ci_available=False,  # AG3-056: conscious opt-out, no live Jenkins
            )
        )

        # 2. Run setup. AK3 owns the story via story_id (no GitHub issue input).
        config = SetupConfig(
            project_root=tmp_path,
            story_id="TEST-001",
            create_worktree=False,  # No git worktree in tmp_path
        )
        _init_repo(tmp_path)
        handler = build_setup_phase_handler(config)

        # Seed the APPROVED Story the Setup preflight gate requires
        # (real StoryService persistence, no mock).
        seed_approved_story(
            project_key="test",
            story_display_id="TEST-001",
            story_number=1,
            story_type=WireStoryType.IMPLEMENTATION,
            title="E2E setup: builds context from Story-Service",
        )

        # AG3-144 (Codex round-3): seed the active ownership record a real
        # control-plane setup start would mint. Setup's ARE-bundle-load write
        # is fenced (7b68f2fc); this handler is driven directly (no
        # control-plane), so the lease must already be active when
        # ``handler.on_enter`` runs. ``run_id`` matches the ``PhaseState``
        # below (the fence's run_id predicate input).
        run_id = "11111111-1111-4111-8111-111111111111"
        seed_active_run_ownership(
            project_key="test",
            story_id="TEST-001",
            run_id=run_id,
        )

        # Minimal initial context
        ctx = StoryContext(
            project_key="test",
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )
        state = make_phase_state(
            story_id="TEST-001",
            phase="setup",
            status=PhaseStatus.IN_PROGRESS,
            run_id=run_id,
        )

        result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status == PhaseStatus.COMPLETED

        # 3. Verify context.json was written from the Story-Service record.
        s_dir = story_dir(tmp_path, "TEST-001")
        loaded = read_story_context_record(s_dir)
        assert loaded is not None
        assert loaded.story_id == "TEST-001"
        assert loaded.title == "E2E setup: builds context from Story-Service"

    def test_setup_fails_on_unknown_story(
        self,
        tmp_path: Path,
    ) -> None:
        """Setup fails closed when the story is unknown to the Story-Service.

        No Story-Service record is seeded, so the preflight STORY_EXISTS check
        fails closed -- the fail-closed identity gate now rests on the AK3
        story identity (story_id), not on a GitHub issue (AG3-120).
        """
        install_agentkit(
            InstallConfig(
                project_key="test",
                project_name="test",
                project_root=tmp_path,
                github_owner="acme",  # AG3-039 R6: CP 7 coordinates are MANDATORY
                github_repo="demo",
                sonarqube_available=False,  # AG3-052: conscious opt-out, no live Sonar
                ci_available=False,  # AG3-056: conscious opt-out, no live Jenkins
            )
        )

        config = SetupConfig(
            project_root=tmp_path,
            story_id="FAIL-001",
        )
        _init_repo(tmp_path)
        handler = build_setup_phase_handler(config)
        ctx = StoryContext(
            project_key="test",
            story_id="FAIL-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )
        state = make_phase_state(
            story_id="FAIL-001",
            phase="setup",
            status=PhaseStatus.IN_PROGRESS,
        )

        result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))
        assert result.status == PhaseStatus.FAILED
        assert len(result.errors) > 0
