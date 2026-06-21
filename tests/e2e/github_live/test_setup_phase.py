"""E2E tests for the setup phase against the live GitHub testbed.

Testbed: saltenhof/agentkit3-testbed
Pre-existing issues: #1 (implementation), #2 (bugfix), #3 (concept).
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from tests.e2e._helpers import seed_approved_story

from agentkit.backend.bootstrap.composition_root import build_setup_phase_handler
from agentkit.backend.governance.setup_preflight_gate.phase import SetupConfig
from agentkit.backend.installer import InstallConfig, install_agentkit
from agentkit.backend.installer.paths import story_dir
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.pipeline_engine.phase_executor import (
    PhaseState,
    PhaseStatus,
)
from agentkit.backend.state_backend.store import read_story_context_record
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import WireStoryType
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


OWNER = "saltenhof"
REPO = "agentkit3-testbed"


def _init_repo(root: Path) -> None:
    """Init a real git repo (Preflight Check 7 reads it, AG3-034 Finding B)."""
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "t@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)


@pytest.mark.e2e
@pytest.mark.requires_gh
class TestSetupPhaseE2E:
    """End-to-end tests for the setup phase against real GitHub."""

    def test_setup_reads_real_issue(self, tmp_path: Path) -> None:
        """Setup phase reads testbed issue #1 and builds StoryContext."""
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

        # 2. Run setup with real issue
        config = SetupConfig(
            owner=OWNER,
            repo=REPO,
            issue_nr=1,
            project_root=tmp_path,
            create_worktree=False,  # No git repo in tmp_path
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
            title="E2E setup: reads real issue",
        )

        # Minimal initial context
        ctx = StoryContext(
            project_key="test",
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )
        state = PhaseState(
            story_id="TEST-001",
            phase="setup",
            status=PhaseStatus.IN_PROGRESS,
        )

        result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status == PhaseStatus.COMPLETED

        # 3. Verify context.json was written
        s_dir = story_dir(tmp_path, "TEST-001")
        loaded = read_story_context_record(s_dir)
        assert loaded is not None
        assert loaded.issue_nr == 1
        assert loaded.story_id == "TEST-001"

    def test_setup_preflight_fails_on_nonexistent_issue(
        self,
        tmp_path: Path,
    ) -> None:
        """Setup fails cleanly when issue doesn't exist."""
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
            owner=OWNER,
            repo=REPO,
            issue_nr=99999,
            project_root=tmp_path,
        )
        _init_repo(tmp_path)
        handler = build_setup_phase_handler(config)
        ctx = StoryContext(
            project_key="test",
            story_id="FAIL-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )
        state = PhaseState(
            story_id="FAIL-001",
            phase="setup",
            status=PhaseStatus.IN_PROGRESS,
        )

        result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))
        assert result.status == PhaseStatus.FAILED
        assert len(result.errors) > 0
